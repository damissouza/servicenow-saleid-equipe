"""Importa o historico local no painel privado; nao acessa o ServiceNow."""
import argparse
import getpass
from http.cookiejar import CookieJar
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
SITE = 'https://historico-venda-ativa.vercel.app'
FIELDS = ('chamado', 'franquia', 'matricula', 'cpf', 'uc', 'data_abertura', 'data_atribuicao', 'data_resolucao')
LIMIT = 3 * 1024 * 1024


class SameSiteRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != 'https' or urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(SITE).netloc:
            raise ValueError('Redirecionamento para fora do painel recusado.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_payload(path):
    with Path(path).open('rb') as file:
        content = file.read(LIMIT + 1)
    if len(content) > LIMIT:
        raise ValueError('Historico maior que 3 MB; nenhum envio realizado.')
    data = json.loads(content.decode('utf-8-sig'))
    if data.get('schema_version') != 1 or data.get('marcador', '').strip().casefold() != 'venda ativa' or not isinstance(data.get('rows'), list) or not data['rows']:
        raise ValueError('Use o historico de Venda Ativa concluido e revisado.')
    rows = []
    for row in data['rows']:
        if not isinstance(row, dict):
            raise ValueError('Registro invalido no historico.')
        projected = {key: row.get(key, '') for key in FIELDS}
        if any(not isinstance(value, str) for value in projected.values()):
            raise ValueError('CPF, UC e os demais campos devem ser texto.')
        if not projected['matricula'] or not projected['data_resolucao']:
            raise ValueError('Ha registro sem matricula ou data de resolucao; conclua a revisao local.')
        rows.append(projected)
    return {'schema_version': 1, 'marcador': 'Venda Ativa', 'rows': rows}


def publish(data, email, password, opener=None):
    cookies = CookieJar()
    client = opener or urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies), SameSiteRedirect())
    headers = {'Origin': SITE, 'X-Requested-With': 'historico-venda-ativa'}
    login = urllib.request.Request(SITE + '/auth/start', data=urllib.parse.urlencode({'email': email, 'password': password}).encode(), headers={**headers, 'Content-Type': 'application/x-www-form-urlencoded'})
    with client.open(login, timeout=30) as response:
        response.read(65536)
    request = urllib.request.Request(SITE + '/api/historico', headers=headers)
    with client.open(request, timeout=30) as response:
        version_data = json.loads(response.read(LIMIT + 4096))
    version = version_data.get('version')
    if not isinstance(version, str):
        raise ValueError('O painel nao retornou a versao atual. Nenhum envio realizado.')
    body = json.dumps({'data': data, 'version': version}, ensure_ascii=False).encode('utf-8')
    if len(body) > LIMIT:
        raise ValueError('Envio maior que o limite do painel.')
    request = urllib.request.Request(SITE + '/api/historico/importar', data=body, headers={**headers, 'Content-Type': 'application/json'}, method='POST')
    with client.open(request, timeout=60) as response:
        return json.loads(response.read(65536))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--conferir', action='store_true', help='Valida o arquivo e mostra contagens; sem rede ou envio.')
    args = parser.parse_args()
    if (ROOT / 'saleid/saida/historico_venda_ativa_pendente.json').exists():
        raise ValueError('Ha revisao pendente. Execute revisar_historico.py antes de publicar.')
    data = read_payload(ROOT / 'saleid/saida/historico_venda_ativa.json')
    calls = len({row['chamado'] for row in data['rows']})
    print(f'{len(data["rows"])} registros de {calls} chamados revisados para o painel da equipe.')
    if args.conferir:
        print('Conferencia local concluida. Nenhum envio realizado.')
        return
    if input('Digite PUBLICAR para importar no painel privado: ').strip() != 'PUBLICAR':
        raise ValueError('Publicacao cancelada. Nenhum envio realizado.')
    config = json.loads((ROOT / 'saleid/config_resolucao.json').read_text(encoding='utf-8'))
    email = input('E-mail autorizado no painel (Enter usa o e-mail de atribuicao): ').strip() or config['assignee_email']
    password = getpass.getpass('Senha da equipe no painel (nao sera salva): ')
    result = publish(data, email, password)
    print('Importacao confirmada: '+str(result.get('added', 0))+' novos; '+str(result.get('enriched', 0))+' complementados; '+str(result['total'])+' registros no painel.')
    if result.get('backupWarning'):
        print('Aviso: a limpeza de backups antigos nao foi concluida; o envio foi confirmado.')
    print('Nenhum chamado foi alterado no ServiceNow por este publicador.')


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as exc:
        messages = {401: 'Acesso ao painel expirado ou nao autorizado.', 403: 'E-mail/senha recusados ou origem nao autorizada.', 409: 'Versao alterada ou dados conflitantes. Confira o painel com a responsavel antes de reenviar.', 429: 'Muitas tentativas de login; aguarde o prazo indicado no painel.'}
        raise SystemExit(messages.get(exc.code, 'Painel recusou a importacao (HTTP '+str(exc.code)+'). Nao houve reenvio automatico.')) from None
    except (OSError, ValueError, KeyError, KeyboardInterrupt, EOFError):
        raise SystemExit('Publicacao nao confirmada. Confira o arquivo/configuracao e a versao no painel antes de reenviar. Nao execute aplicar novamente.') from None
