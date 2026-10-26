"""Prepara apenas arquivos locais. Nao acessa ServiceNow, navegador ou painel."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent


def prepare(directory, email, name, instance, reference_incident, reference_ritm, marker_references):
    directory = Path(directory)
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise ValueError('Informe seu e-mail corporativo valido.')
    if not name.strip() or any(c in name for c in '\r\n{}'):
        raise ValueError('Informe seu nome para a assinatura.')
    url = urlsplit(instance.strip())
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
        raise ValueError('Use somente a origem HTTPS da instancia, sem caminho ou credenciais.')
    incident = reference_incident.strip().upper()
    ritm = reference_ritm.strip().upper()
    if not re.fullmatch(r'INC\d{7,}', incident):
        raise ValueError('Informe um INC real ja resolvido ou encerrado com a resolucao aprovada.')
    if ritm and not re.fullmatch(r'RITM\d{7,}', ritm):
        raise ValueError('Referencia RITM invalida.')
    references = list(dict.fromkeys(v.upper() for v in re.split(r'[\s,;]+', marker_references.strip()) if v))
    if any(not re.fullmatch(r'(?:INC|RITM)\d{7,}', v) for v in references):
        raise ValueError('Referencia de marcador invalida.')
    files = ['config_resolucao.json', 'config_conexao_historico_venda_ativa.json', 'config_inspecao.json', 'resposta_resolucao.txt', 'incidentes.txt']
    if any((directory / filename).exists() for filename in files):
        raise ValueError('Ja existem arquivos locais. Edite-os diretamente; a configuracao inicial nao sobrescreve dados.')
    configs = {filename: json.loads((directory / filename.replace('.json', '.example.json')).read_text(encoding='utf-8')) for filename in files[:3]}
    config = configs['config_resolucao.json']
    marker = next((value for value in config.get('resolution_confirmed_markers', []) if value.casefold() == 'venda ativa'), 'Venda Ativa')
    config.update(assignee_email=email.strip(), reference_incident=incident, reference_ritm=ritm,
                  selection_tag_references={marker: references})
    connection = configs['config_conexao_historico_venda_ativa.json']
    connection.update(instance_url='https://' + url.netloc, profile_dir=str(directory.parent / '.brave_perfil'))
    response = (directory / 'resposta_resolucao.example.txt').read_text(encoding='utf-8').replace('{{NOME_ANALISTA}}', name.strip())
    if '{{' in response:
        raise ValueError('A resposta ainda possui campos nao preenchidos.')
    for filename, value in configs.items():
        (directory / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (directory / 'resposta_resolucao.txt').write_text(response, encoding='utf-8')
    (directory / 'incidentes.txt').write_text('', encoding='utf-8')
    (directory / 'saida').mkdir(exist_ok=True)
    if (directory / 'favicon.ico').exists():
        (directory / 'saida/favicon.ico').write_bytes((directory / 'favicon.ico').read_bytes())
    return files


def main():
    print('Configuracao local. Nenhum chamado sera lido ou alterado.')
    email = input('Seu e-mail corporativo de atribuicao: ').strip()
    name = input('Seu nome para assinar a resposta: ').strip()
    instance = input('Origem HTTPS do ServiceNow: ').strip()
    incident = input('INC de referencia ja resolvido/encerrado com os campos aprovados: ').strip()
    ritm = input('RITM de referencia Encerrado concluido (Enter para configurar depois): ').strip()
    references = input('Chamados reais que possuem Venda Ativa, separados por virgula (Enter se label for acessivel): ').strip()
    prepare(ROOT / 'saleid', email, name, instance, incident, ritm, references)
    print('Arquivos locais criados. Revise config_resolucao.json e resposta_resolucao.txt antes de prever.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyboardInterrupt, EOFError) as exc:
        raise SystemExit('Configuracao interrompida: ' + str(exc))
