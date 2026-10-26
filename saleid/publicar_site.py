"""Publicacao local -> painel; nunca altera chamados no ServiceNow."""
import argparse
from datetime import datetime, timezone
import getpass
import hashlib
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
SITE = 'https://historico-venda-ativa.vercel.app'
FIELDS = ('chamado', 'franquia', 'matricula', 'cpf', 'uc', 'data_abertura', 'data_atribuicao', 'data_resolucao')
LIMIT = 3 * 1024 * 1024
STATE = 'publicacao_site.json'

class SameSiteRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != 'https' or urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(SITE).netloc:
            raise ValueError('Redirecionamento para fora do painel recusado.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_payload(path, *, skip_incomplete=False):
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
            if skip_incomplete:
                continue
            raise ValueError('Ha registro sem matricula ou data de resolucao; conclua a revisao local.')
        rows.append(projected)
    if not rows:
        raise ValueError('Nao ha registros completos para publicar.')
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


class PublicationPending(RuntimeError):
    pass


def save_state(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix='.publicacao-', suffix='.tmp', delete=False) as file:
        temporary = Path(file.name)
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


def synchronize(root, config=None, *, password_fn=None, publish_fn=None):
    """Uma tentativa autenticada; falha fica pendente, sem repetir resolucoes."""
    root = Path(root)
    out = root / 'saida'
    state_path = out / STATE
    metadata = None
    try:
        if (out / 'historico_venda_ativa_pendente.json').exists():
            raise ValueError('Revisao local ainda pendente.')
        if state_path.exists():
            old = json.loads(state_path.read_text(encoding='utf-8'))
            if not isinstance(old, dict) or old.get('schema_version') != 1:
                raise ValueError('Registro de publicacao invalido; preserve-o para conferencia.')
        path = out / 'historico_venda_ativa.json'
        data = read_payload(path, skip_incomplete=True)
        original_count = len(json.loads(path.read_text(encoding='utf-8-sig'))['rows'])
        skipped = original_count - len(data['rows'])
        if config is None:
            config = json.loads((root / 'config_resolucao.json').read_text(encoding='utf-8-sig'))
        email = config.get('panel_email') or config['assignee_email']
        if not isinstance(email, str) or not email.strip():
            raise ValueError('E-mail de acesso ausente.')
        metadata = dict(schema_version=1, status='pending',
                        attempted_at=datetime.now(timezone.utc).isoformat(),
                        digest=hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                        rows=len(data['rows']), skipped=skipped)
        save_state(state_path, metadata)
        if skipped:
            print(f'{skipped} registro(s) antigo(s) sem matricula/data permanecem locais; nao serao reenviados nem removidos do painel.', flush=True)
        print('Historico local salvo. Publicando automaticamente no painel da equipe...', flush=True)
        password = (password_fn or getpass.getpass)('Senha da equipe no painel (nao sera salva): ')
        if not password:
            raise ValueError('Senha nao informada.')
        result = (publish_fn or publish)(data, email, password)
        if (not isinstance(result, dict) or not isinstance(result.get('total'), int)
                or result.get('total', 0) < len(data['rows'])):
            raise ValueError('Resposta de publicacao nao confirmada.')
        save_state(state_path, dict(metadata, status='confirmed',
                    confirmed_at=datetime.now(timezone.utc).isoformat(),
                    added=result.get('added', 0), enriched=result.get('enriched', 0), total=result['total']))
        print(f"Site atualizado: {result.get('added', 0)} novos; {result.get('enriched', 0)} complementados; {result['total']} registros compartilhados.", flush=True)
        if result.get('backupWarning'):
            print('Publicacao confirmada; a limpeza de backups antigos ficou pendente.', flush=True)
        return result
    except (Exception, KeyboardInterrupt) as exc:
        code = 'interrupted' if isinstance(exc, (KeyboardInterrupt, EOFError)) else 'local_validation'
        if isinstance(exc, urllib.error.HTTPError):
            code = 'http_' + str(exc.code)
        elif isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError)):
            code = 'network_uncertain'
        if metadata is not None:
            try:
                save_state(state_path, dict(metadata, status='pending', reason=code))
            except OSError:
                pass
        raise PublicationPending('Historico local preservado; publicacao no site nao confirmada (' + code +
            '). Retome somente publicar_site.py. Nao repita aplicar para publicar.') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--conferir', action='store_true', help='Somente valida o historico local; sem rede ou gravacao.')
    args = parser.parse_args()
    if args.conferir:
        data = read_payload(ROOT / 'saida/historico_venda_ativa.json', skip_incomplete=True)
        print(f'{len(data["rows"])} registros completos para publicar. Nenhum envio realizado.')
        return 0
    import bulk_update as base
    with base.execution_lock():
        synchronize(ROOT)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (PublicationPending, OSError, ValueError, KeyboardInterrupt, EOFError) as exc:
        raise SystemExit(str(exc)) from None


