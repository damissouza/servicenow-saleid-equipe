"""Inspeção somente de leitura: lista identificada, matrícula e franquia no Workspace."""
# Permite executar diretamente os scripts nas pastas por função.
import sys as _sys
from pathlib import Path as _Path
_project_root = _Path(__file__).resolve().parent
_sys.path.insert(0, str(_project_root))

import argparse
import html
import re
import sys
from contextlib import nullcontext
from pathlib import Path
import bulk_update as base
from numeros_chamados import parse_numbers, table_for

ROOT = base.ROOT


def registration_from_text(texts, allow_multiple=False):
    values = set()
    pattern = re.compile(r'\bmatr[íi]cula(?:\s+do\s+(?:titular|filiado|associado))?'
                         r'[ \t]*(?:[:=\-–][ \t]*|\r?\n[ \t]*|[ \t]+)'
                         r'([0-9A-Za-z][0-9A-Za-z./\-]*)', re.I)
    # Formato conhecido do CTN: UF seguida por nove dígitos. Números sem
    # rótulo não são inferidos, para evitar capturar CPF, telefone ou contrato.
    ctn = re.compile(r'(?<![\w/-])(?:AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)[0-9]{9}(?![\w/])', re.I)
    for text in texts:
        text = html.unescape(re.sub(r'<[^>]*>', ' ', text or ''))
        for match in pattern.finditer(text):
            value = match.group(1).rstrip('./-').upper()
            if re.fullmatch(r'[0-9]+(?:[./-][0-9]+)*', value) or ctn.fullmatch(value):
                values.add(value)
        values.update(match.group().upper() for match in ctn.finditer(text))
    if len(values) == 1:
        return next(iter(values)), ''
    if len(values) > 1:
        if allow_multiple:
            return '; '.join(sorted(values)), ''
        return '', 'Mais de uma matrícula identificada na Descrição; conferir manualmente'
    return '', 'Matrícula não identificada na Descrição; conferir manualmente'


def ritm_registration_texts(client, record):
    """Descrição e comentários públicos da RITM e das SCTASKs vinculadas; somente GET."""
    from selecao_marcador import pages
    ident = base.sys_id(base.raw(record['sys_id']))
    texts = [base.raw(record.get('description')), base.display(record.get('comments'))]
    sources = [ident]
    for task in pages(client, 'sc_task', 'request_item=' + ident, 'sys_id,request_item,comments'):
        if base.raw(task.get('request_item')) != ident:
            raise base.Stop('SCTASK retornada não pertence à RITM inspecionada.')
        sources.append(base.sys_id(base.raw(task['sys_id'])))
        texts.append(base.display(task.get('comments')))
    for source in sources:
        for comment in pages(client, 'sys_journal_field', 'element_id=' + source + '^element=comments',
                             'sys_id,element_id,element,value'):
            if base.raw(comment.get('element_id')) != source or base.raw(comment.get('element')) != 'comments':
                raise base.Stop('Comentário retornado não pertence ao chamado inspecionado.')
            texts.append(base.raw(comment.get('value')))
    return texts


def read_registration_description(page, description=''):
    texts = [description]
    for name in ('variables.v_description', 'variables.description', 'description'):
        locator = page.locator(f'textarea[name="{name}"]')
        for i in range(locator.count()):
            item = locator.nth(i)
            if item.is_visible():
                texts.append(item.input_value())
    return registration_from_text(texts, allow_multiple=True)


def read_field(page, selectors, labels, allow_multiple=False):
    values = set()
    for selector in selectors:
        locator = page.locator(selector)
        for i in range(locator.count()):
            item = locator.nth(i)
            if item.is_visible():
                value = item.input_value().strip()
                if value:
                    values.add(value)
    if not values:
        for label in labels:
            locator = page.get_by_label(re.compile(label, re.I))
            for i in range(locator.count()):
                item = locator.nth(i)
                if item.is_visible() and item.evaluate('(el) => ["INPUT","TEXTAREA","SELECT"].includes(el.tagName)'):
                    value = item.evaluate('(el) => el.tagName === "SELECT" ? el.selectedOptions[0]?.textContent || "" : el.value').strip()
                    if value:
                        values.add(value)
    if len(values) > 1:
        if allow_multiple:
            return '; '.join(sorted({v.upper() for v in values})), ''
        return '', 'Mais de um valor encontrado; conferir manualmente'
    return (next(iter(values)), '') if values else ('', 'Campo vazio ou não localizado')


def combine_registrations(field_value, described):
    values = set()
    for source in (field_value, described):
        for value in source.split(';'):
            value = value.strip()
            if not value:
                continue
            extracted, _ = registration_from_text([value], allow_multiple=True)
            values.update(extracted.split('; ') if extracted else [value.upper()])
    return sorted(values)


def export(rows):
    output = ROOT / 'saida'
    output.mkdir(exist_ok=True)
    base.save_json(output / 'inspecao_matriculas.json', rows)
    lines = ['Chamado\tMatrícula\tFranquia\tResultado']
    for row in rows:
        lines.append('\t'.join(str(row[k]).replace('\t',' ').replace('\n',' ') for k in ('chamado','matricula','franquia','resultado')))
    (output / 'inspecao_matriculas.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8-sig')
    table = ''.join('<tr>' + ''.join('<td>'+html.escape(str(r[k]))+'</td>' for k in ('chamado','matricula','franquia','resultado'))+'</tr>' for r in rows)
    (output / 'inspecao_matriculas.html').write_text('<!doctype html><meta charset="utf-8"><title>Inspeção de chamados</title><style>body{font:16px system-ui;margin:32px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:10px;text-align:left}th{background:#eef5f1}</style><h1>Matrículas e franquias</h1><p>Inspeção de leitura. Campos vazios precisam de conferência.</p><table><tr><th>Chamado</th><th>Matrícula</th><th>Franquia</th><th>Resultado</th></tr>'+table+'</table>', encoding='utf-8')


def tab_control(page, number):
    table_for(number)
    return page.locator(f'button[aria-label="Fechar guia {number}"]')


def record_tab(page, number):
    return page.locator('a[role="tab"]').filter(has_text=re.compile('^' + re.escape(number) + '$'))


def check_capacity(page, number):
    existing = tab_control(page, number).count() > 0 or record_tab(page, number).count() > 0
    if not existing and page.locator('button[aria-label^="Fechar guia "]').count() >= 8:
        raise base.Stop('Workspace já está com 8 guias. Feche uma guia manualmente e execute novamente.')
    return existing


def close_owned_tab(page, number):
    tab = record_tab(page, number)
    if tab.count():
        base.visible_one(tab, 'Guia ' + number).hover(timeout=5000)
    control = tab_control(page, number)
    control.first.wait_for(state='visible', timeout=5000)
    base.visible_one(control, 'Fechar guia ' + number).click(timeout=5000)
    control.first.wait_for(state='detached', timeout=10000)
    tab.first.wait_for(state='detached', timeout=10000)


def inspect(client, connection, numbers, fields_config, quiet=False, include_ritm=True,
            enrich=False, on_result=None, export_results=True, navigation_lock=None):
    emit = (lambda *args, **kwargs: None) if quiet else print
    # O Workspace persiste guias internas mesmo entre navegações da aba do navegador.
    source = getattr(client.page, 'page', client.page)
    page = source.context.new_page()
    rows = []
    def completed(result):
        rows.append(result)
        if export_results:
            export(rows)
        if on_result:
            on_result(result)
    try:
        page.goto(source.url, wait_until='domcontentloaded')
        page.locator('a#tab_0').wait_for(state='visible', timeout=30000)
        for index, number in enumerate(numbers, 1):
            emit(f'Conferindo {index}/{len(numbers)}: {number}', flush=True)
            result = dict(chamado=number, matricula='', matriculas=[], franquia='', resultado='')
            if table_for(number) == 'sc_req_item':
                result['resultado'] = 'Validação manual (RITM não inspecionada)'
                if include_ritm:
                    try:
                        fields = 'sys_id,number,description,comments' + (',opened_by,opened_at' if enrich else '')
                        records = client.rows('sc_req_item', 'number=' + number, fields, 2)
                        if len(records) != 1 or base.raw(records[0].get('number')) != number:
                            raise base.Stop('RITM não encontrada de forma única.')
                        texts = ritm_registration_texts(client, records[0])
                        value, error = registration_from_text(texts, allow_multiple=True)
                        result['matricula'] = value
                        result['matriculas'] = value.split('; ') if value else []
                        result['resultado'] = error or 'Matrículas extraídas da Descrição/comentários da RITM e SCTASK; franquia manual'
                        if enrich:
                            from dados_previsao import cpf_associations
                            result['franquia'] = base.display(records[0].get('opened_by'))
                            result['data_abertura'] = base.display(records[0].get('opened_at'))
                            candidates = {m:set() for m in result['matriculas']}
                            for text in texts:
                                for m,cpf in cpf_associations(text, result['matriculas']).items():
                                    if cpf:
                                        candidates[m].add(cpf)
                            result['cpfs'] = {m:next(iter(values)) if len(values) == 1 else '' for m,values in candidates.items()}
                            result['resultado'] = error or ('Conferido' if result['franquia'] else 'Franquia não localizada em Aberto por')
                    except Exception as exc:
                        result['resultado'] = 'RITM: ' + str(exc)[:500]
                completed(result)
                emit(result['resultado'], flush=True)
                continue
            opened = False
            stop_batch = False
            try:
                table = table_for(number)
                records = client.rows(table, 'number=' + number, 'sys_id,number,description' + (',opened_at' if enrich else ''), 2)
                if len(records) != 1 or base.raw(records[0].get('number')) != number:
                    raise base.Stop('Registro não encontrado de forma única.')
                ident = base.sys_id(base.raw(records[0]['sys_id']))
                with navigation_lock or nullcontext():
                    existing = check_capacity(page, number)
                    if existing:
                        tab = record_tab(page, number)
                        base.visible_one(tab, 'Guia ' + number).click()
                    else:
                        opened = True
                        page.goto(connection['origin'] + '/now/sow/record/' + table + '/' + ident, wait_until='domcontentloaded')
                    # Aguarda registro da guia antes de outro trabalhador abrir.
                    if navigation_lock:
                        record_tab(page, number).first.wait_for(state='visible', timeout=20000)
                details = page.get_by_role('tab', name='Detalhes', exact=True)
                details.first.wait_for(state='visible', timeout=30000)
                base.visible_one(details, 'Detalhes').click()
                number_field = page.locator('input[name="number"]')
                number_field.first.wait_for(state='visible', timeout=20000)
                if base.visible_one(number_field, 'Número').input_value().strip() != number:
                    raise base.Stop('O formulário não corresponde ao chamado solicitado.')
                # Aguarda o campo de variável conhecido; depois tenta rótulos acessíveis.
                try:
                    page.locator(','.join(fields_config['matricula_selectors'] + fields_config['franquia_selectors'])).first.wait_for(state='visible', timeout=10000)
                except Exception:
                    pass
                errors = []
                from_description = False
                for field in ('matricula', 'franquia'):
                    value, error = read_field(page, fields_config[field+'_selectors'], fields_config[field+'_labels'], allow_multiple=field == 'matricula')
                    if field == 'matricula' and error == 'Campo vazio ou não localizado':
                        # Variáveis de catálogo carregam depois do restante do
                        # formulário. Esperar a matrícula, não apenas a franquia.
                        for attempt in range(10):
                            page.wait_for_timeout(500)
                            value, error = read_field(page, fields_config[field+'_selectors'], fields_config[field+'_labels'], allow_multiple=True)
                            if error != 'Campo vazio ou não localizado':
                                break
                    if field == 'matricula':
                        described, description_error = read_registration_description(page, base.raw(records[0].get('description')))
                        result['matriculas'] = combine_registrations(value, described)
                        value = '; '.join(result['matriculas'])
                        error = '' if value else description_error or error
                        from_description = bool(described)
                    result[field] = value
                    if error:
                        errors.append(field + ': ' + error)
                result['resultado'] = '; '.join(errors) or 'Conferido'
                if from_description:
                    result['resultado'] += ' | Matrículas reunidas do campo e da Descrição, sem duplicidade'
                if enrich:
                    from dados_previsao import cpf_associations
                    cpf_value, _ = read_field(page, ['input[name="variables.cpf"]', 'input[name="variables.u_cpf"]'], [r'^CPF\s*[:*]?(?:\. Este campo.*)?$'])
                    result['cpfs'] = cpf_associations(base.raw(records[0].get('description')), result['matriculas'], cpf_value)
                    result['data_abertura'] = base.display(records[0].get('opened_at'))
                if errors:
                    # Apenas metadados dos controles para ajustar seletores, sem valores pessoais.
                    controls = page.locator('input,textarea,select').evaluate_all('(els) => els.filter(e => e.getClientRects().length).map(e => ({tag:e.tagName,name:e.name,id:e.id,label:e.getAttribute("aria-label")}))')
                    base.save_json(ROOT / 'saida' / ('campos_' + number + '.json'), controls)
            except Exception as exc:
                result['resultado'] = str(exc)[:700]
                stop_batch = True
            finally:
                if opened:
                    try:
                        with navigation_lock or nullcontext():
                            close_owned_tab(page, number)
                    except Exception as exc:
                        result['resultado'] += ' | Não foi possível fechar a guia criada: ' + str(exc)[:250]
                        stop_batch = True
            if enrich and stop_batch:
                result['_stop_batch'] = True
            completed(result)
            emit(result['resultado'], flush=True)
            if stop_batch:
                emit('Inspeção interrompida para não acumular guias. Relatório parcial preservado.')
                break
    finally:
        page.close()
    emit('Relatórios: saida/inspecao_matriculas.txt e saida/inspecao_matriculas.html')

    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lista', type=Path, help='Lista da inspeção. No modo de atualização, restringe a busca a esta lista.')
    parser.add_argument('--atualizar-venda-ativa', action='store_true', help='Busca todos os resolvidos/encerrados com a anotação exata, sem filtro de responsável, e atualiza o JSON fixo com backup.')
    parser.add_argument('--referencia', type=Path, help='Tabela TXT tabulada ou JSON de matrícula, franquia, CPF e UC para a atualização.')
    args = parser.parse_args()
    if args.atualizar_venda_ativa:
        import subprocess
        target = ROOT if (ROOT / 'historico_venda_ativa.py').exists() else ROOT.parent / 'historico_venda_ativa'
        command = [sys.executable, str(target / 'fechados_venda_ativa.py')]
        if args.lista:
            path = args.lista if args.lista.is_absolute() else ROOT / args.lista
            command.extend(['--lista', str(path)])
        if args.referencia:
            path = args.referencia if args.referencia.is_absolute() else ROOT / args.referencia
            command.extend(['--referencia', str(path)])
        raise SystemExit(subprocess.run(command).returncode)
    args.lista = args.lista or ROOT / 'saida/chamados_identificados.txt'
    if not args.lista.is_absolute():
        args.lista = ROOT / args.lista
    numbers, _ = parse_numbers(args.lista.read_text(encoding='utf-8-sig'))
    connection = base.load_config(ROOT / 'config_conexao_historico_venda_ativa.json')
    fields_config = base.read_json(ROOT / 'config_inspecao.json')
    with base.execution_lock(), base.connected(connection) as client:
        rows = inspect(client, connection, numbers, fields_config, include_ritm=True)
        total = sum(len(row.get('matriculas', [])) for row in rows)
        print(f'Resumo: {len(rows)} chamados inspecionados; {total} matrículas identificadas.')
        for row in rows:
            print(row['chamado'] + ': ' + (row['matricula'] or 'matrícula não identificada'))


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    try:
        main()
    except (base.Stop, OSError, ValueError, KeyError) as exc:
        print('Interrompido: ' + str(exc), file=sys.stderr)
        raise SystemExit(2)
