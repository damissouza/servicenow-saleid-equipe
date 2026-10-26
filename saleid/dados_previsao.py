"""Associação conservadora de CPF e geração do relatório de leitura."""
import html
import re


def franchise_for_html(value):
    """Corrige só a exibição autorizada; nunca modifica o valor da prévia."""
    text = str(value or '')
    # Reconhece assinaturas de bytes UTF-8 interpretados como Windows-1252/Latin-1.
    pattern = re.compile(r'(?:Ã[\u0080-\u00bf\u0152\u0153\u0160\u0161\u0178\u0192]|Â[\u0080-\u00bf]|â[€‚„])')
    for _ in range(2):
        score = len(pattern.findall(text))
        if not score:
            break
        candidates = []
        for encoding in ('cp1252','latin-1'):
            try:
                candidate = text.encode(encoding,errors='strict').decode('utf-8',errors='strict')
            except (UnicodeEncodeError,UnicodeDecodeError):
                continue
            if '\ufffd' not in candidate and len(pattern.findall(candidate)) < score:
                candidates.append(candidate)
        if not candidates:
            break
        text = min(candidates,key=lambda candidate:len(pattern.findall(candidate)))
    return text or '—'


def cpf_associations(description, registrations, field_cpf=''):
    associations = {r:'' for r in registrations}
    cpf_pattern = r'(?<!\d)(\d{3}\.?\d{3}\.?\d{3}-?\d{2})(?!\d)'
    def formatted(value):
        match = re.fullmatch(cpf_pattern, value.strip())
        if not match:
            return ''
        digits = re.sub(r'\D', '', match.group(1))
        return f'{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}'
    text = html.unescape(re.sub(r'<[^>]*>', '\n', description or ''))
    candidates = {r:set() for r in registrations}
    # Somente pares explicitamente rotulados no mesmo trecho/linha.
    for line in text.splitlines():
        matriculas = re.findall(r'matr[íi]cula\s*[:=]\s*([A-Za-z0-9]+)', line, re.I)
        cpfs = re.findall(r'\bCPF\s*[:=]\s*' + cpf_pattern, line, re.I)
        if len(matriculas) == len(cpfs) == 1:
            registration = matriculas[0].upper()
            if registration in candidates and formatted(cpfs[0]):
                candidates[registration].add(formatted(cpfs[0]))
    if len(registrations) == 1 and formatted(field_cpf):
        candidates[registrations[0]].add(formatted(field_cpf))
    return {r:next(iter(values)) if len(values) == 1 else '' for r,values in candidates.items()}


def render_report(root, records, *, basename='previsao_chamados', title='Previsão de chamados', output_dir=None, favicon='favicon.ico', history_columns=False):
    out = output_dir if output_dir is not None else root / 'saida'
    out.mkdir(exist_ok=True)
    rows = []
    for record in records:
        for registration in record.get('matriculas', []) or ['']:
            row = [record['chamado'], franchise_for_html(record.get('franquia','')), registration,
                   record.get('cpfs', {}).get(registration,'')]
            if history_columns:
                row.append(record.get('uc',''))
            row.append(record.get('data_abertura',''))
            if history_columns:
                row.append(record.get('data_atribuicao','') or '—')
                row.append(record.get('data_resolucao','') or '—')
            rows.append(row)
    headers = ('Incidente/Solicitação','Franquia','Matricula','CPF','UC','Data de abertura','Data de atribuição ao analista','Data de resolução') if history_columns else ('Chamado','Franquia','Matrícula','CPF','Data de abertura')
    cells = ''.join('<tr>' + ''.join('<td>' + html.escape(str(v or '')) + '</td>' for v in row) + '</tr>' for row in rows)
    content = ('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
               '<meta name="viewport" content="width=device-width,initial-scale=1">'
               '<title>' + html.escape(title) + ' | Cartão de TODOS</title>'
               '<link rel="icon" href="' + html.escape(favicon,quote=True) + '"><link rel="stylesheet" href="' + html.escape(basename,quote=True) + '.css">'
               '</head><body><main><h1>' + html.escape(title) + '</h1><p class="total">' + str(len(rows)) +
               ' registros · ' + str(len({r['chamado'] for r in records})) + ' chamados</p><div class="table-wrap"><table><thead><tr>'
               + ''.join('<th>' + html.escape(label) + '</th>' for label in headers) +
               '</tr></thead><tbody>' + cells + '</tbody></table></div></main></body></html>')
    (out / (basename + '.html')).write_text(content, encoding='utf-8')
    css = (root / 'previsao_chamados.css').read_text(encoding='utf-8')
    if history_columns:
        css += '\n/* Datas completas no histórico. */\ntd:nth-child(6),td:nth-child(7),td:nth-child(8){white-space:nowrap}\n'
    (out / (basename + '.css')).write_text(css, encoding='utf-8')

