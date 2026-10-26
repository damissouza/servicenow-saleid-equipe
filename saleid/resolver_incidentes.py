"""Resolve INC e encerra RITM da lista, com prévia e diário sem retry de escrita."""
# Permite executar diretamente os scripts nas pastas por função.
import sys as _sys
from pathlib import Path as _Path
_project_root = _Path(__file__).resolve().parent
_sys.path.insert(0, str(_project_root))

import argparse
import time
from datetime import datetime, timezone
import sys
from urllib.parse import urlsplit
import bulk_update as base
from comentar_carteira import resolve_user
from numeros_chamados import parse_numbers, table_for
import selecao_marcador as tags

ROOT = base.ROOT
PLAN = ROOT / 'saida/resolucao_preview.json'
LEDGER = ROOT / 'saida/resolucao_execution.json'
RESOLUTION = 'state,close_code,close_notes,u_resolution_annotation,u_recurring_incident'
FIELDS = 'sys_id,number,active,assigned_to,sys_mod_count,sys_class_name,u_call_type,' + RESOLUTION
TASK_FIELDS = 'sys_id,number,request_item,active,state,assigned_to,sys_mod_count,sys_class_name,close_notes,u_resolution_code,u_resolution_annotation'


def linked_task(client, parent):
    parent_id = base.sys_id(base.raw(parent['sys_id']))
    rows = client.rows('sc_task', 'request_item=' + parent_id + '^active=true', TASK_FIELDS, 2)
    if len(rows) != 1:
        raise base.Stop(f"{base.raw(parent['number'])}: esperada uma única SCTASK ativa; encontradas {len(rows)}. Confira as tarefas vinculadas.")
    task = rows[0]
    if (any(k not in task for k in TASK_FIELDS.split(',')) or
            base.raw(task.get('request_item')) != parent_id or
            base.raw(task.get('sys_class_name')) != 'sc_task' or
            base.raw(task.get('active')) not in ('true', '1')):
        raise base.Stop('Vínculo ou campos da SCTASK não puderam ser conferidos.')
    base.sys_id(base.raw(task['sys_id']))
    return task


def configured_marker(config, marker):
    name = base.safe(marker)
    keys = set(config.get('resolution_confirmed_markers', []))
    keys.update(config.get('selection_tag_references', {}))
    keys.update(config.get('selection_tag_ids', {}))
    matches = [key for key in keys if tags.marker_name(key) == tags.marker_name(name)]
    if len(matches) > 1:
        raise base.Stop('Há nomes equivalentes de marcador duplicados na configuração. Unifique as chaves antes de continuar.')
    return matches[0] if matches else name


def settings(marker=None):
    config = base.read_json(ROOT / 'config_resolucao.json')
    connection = base.read_json(ROOT / 'config_conexao_historico_venda_ativa.json')
    origin = urlsplit(connection['instance_url'])
    cdp = urlsplit(connection['cdp_url'])
    if origin.scheme != 'https' or not origin.hostname or origin.username or origin.password:
        raise base.Stop('Instância HTTPS inválida.')
    if cdp.scheme != 'http' or cdp.hostname not in ('localhost', '127.0.0.1') or cdp.username or cdp.password:
        raise base.Stop('CDP deve apontar para o navegador local.')
    connection.update(origin='https://' + origin.netloc, connection_mode='cdp')
    config['origin'] = connection['origin']
    config['comment'] = (ROOT / config['response_file']).read_text(encoding='utf-8-sig').strip()
    if marker:
        config['selection_marker'] = configured_marker(config, marker)
        numbers = []
    else:
        numbers, _ = parse_numbers((ROOT / config['numbers_file']).read_text(encoding='utf-8-sig'))
    if not config['comment'] or len(numbers) > config['max_incidents'] or config['plan_max_age_minutes'] <= 0:
        raise base.Stop('Texto vazio, lista acima do limite ou validade inválida.')
    return connection, config, numbers


def fields_for(number):
    return FIELDS if table_for(number) == 'incident' else 'sys_id,number,active,assigned_to,sys_mod_count,sys_class_name,state,close_notes,cat_item'


def record(client, number):
    fields = fields_for(number)
    rows = client.rows(table_for(number), 'number=' + base.safe(number), fields, 2)
    if len(rows) != 1 or base.raw(rows[0].get('number')) != number:
        raise base.Stop(f'{number}: registro não encontrado de forma única.')
    row = rows[0]
    if any(k not in row for k in fields.split(',')):
        raise base.Stop(f'{number}: campos necessários não retornados pela API.')
    base.sys_id(base.raw(row['sys_id']))
    if base.raw(row['sys_class_name']) != table_for(number):
        raise base.Stop('Tipo retornado difere do número solicitado.')
    return row


def targets(client, config):
    reference, _ = base.parse_numbers(config['reference_incident'] or '')
    if len(reference) != 1:
        raise base.Stop('Informe um único INC de referência.')
    row = record(client, reference[0])
    state_value = base.raw(row['state'])
    state_label = base.normalized(base.display(row['state']))
    resolved = state_value == '6' and state_label in ('resolvido', 'resolvido(a)', 'resolvida', 'resolved')
    closed = (state_value == '7' and base.raw(row['active']) in ('false', '0')
              and state_label in ('encerrado', 'encerrado(a)', 'encerrada', 'fechado', 'fechado(a)', 'fechada', 'closed'))
    if not (resolved or closed):
        raise base.Stop(f"Referência {reference[0]}: estado retornado {base.display(row['state'])!r} "
                        f"(valor {state_value!r}, ativo {base.raw(row['active'])!r}). "
                        'Use um INC resolvido ou encerrado com os mesmos dados de resolução.')
    if base.normalized(config['state_label']) not in ('resolvido', 'resolvido(a)', 'resolvida', 'resolved'):
        raise base.Stop('O destino dos INC deve continuar sendo Resolvido(a).')
    checks = {'close_code':config['resolution_code_label'],
              'u_resolution_annotation':config['resolution_option_label'],
              'u_recurring_incident':config['recurrent_label']}
    for field, label in checks.items():
        if base.normalized(base.display(row[field])) != base.normalized(label):
            raise base.Stop(f'Referência: {field} não corresponde à configuração.')
    if base.raw(row['u_recurring_incident']) != 'yes':
        raise base.Stop('Referência diverge dos valores de resolução conferidos.')
    if base.raw(row['close_notes']) != config['resolution_option_label']:
        raise base.Stop('close_notes da referência difere da opção de resolução.')
    payload = {k:base.raw(row[k]) for k in RESOLUTION.split(',')}
    # O modelo pode ter sido encerrado depois de resolvido; o destino continua sendo 6.
    # u_call_type=incident conferido no diagnóstico do INC de referencia.
    payload.update(state='6', u_call_type='incident', assigned_to=resolve_user(client, config), comments=config['comment'])
    return payload


def ritm_targets(client, config):
    number = config.get('reference_ritm', '')
    if table_for(number) != 'sc_req_item':
        raise base.Stop('Configure reference_ritm com uma RITM concluída.')
    row = record(client, number)
    if (base.raw(row['state']) != '3' or base.raw(row['active']) != 'false'
            or base.normalized(base.display(row['state'])) != 'encerrado concluido'):
        raise base.Stop('RITM de referência não está em Encerrado concluído/inativa.')
    notes = config['ritm_close_notes']
    if not notes.strip():
        raise base.Stop('Preencha ritm_close_notes para enviar à SCTASK.')
    return dict(state='3', active='false', close_notes=notes,
                assigned_to=resolve_user(client, config), comments=config['comment'],
                u_resolution_code='resolution code',
                u_resolution_annotation='9f386b6787fa871089470e530cbb3526')


def batch_targets(client, config, numbers):
    tables = {table_for(n) for n in numbers}
    return {t: (targets(client, config) if t == 'incident' else ritm_targets(client, config))
            for t in sorted(tables)}


def eligible(row):
    number = base.raw(row['number'])
    if table_for(number)=='sc_req_item' and tags.pending_ritm(row):
        raise base.Stop(f'{number}: RITM em Pendente não pode ser concluída neste lote.')
    state = base.raw(row['state'])
    allowed = state in ('1', '2', '3') if table_for(number) == 'incident' else bool(state) and state != '3'
    if base.raw(row['active']) not in ('true', '1') or not allowed:
        raise base.Stop(f'{number}: estado/atividade não permite concluir este item.')


def key(config, row):
    # Uma tentativa de resolução bloqueia novos envios, mesmo se o texto mudar.
    return base.digest({'origin':config['origin'], 'sys_id':base.raw(row['sys_id'])})


def resumable_local_save(entry):
    if (entry.get('status') == 'local_preflight_blocked'
            and entry.get('reconciliation', {}).get('confirmed_no_closure_sent') is True
            and entry.get('error') == 'SCTASK permite somente leitura ou encerramento concluído com campos conferidos.'
            and entry.get('task_after_assignment') and not entry.get('task_after')):
        return True
    return (entry.get('status') == 'uncertain' and entry.get('stage') == 'sending_task'
            and '[WinError 5]' in entry.get('error', '')
            and 'resolucao_execution.tmp' in entry.get('error', '')
            and 'resolucao_execution.json' in entry.get('error', '')
            and bool(entry.get('task_after_assignment')) and not entry.get('task_after'))


def verify_resume_task(client, row, previous):
    task = linked_task(client, row)
    expected = previous['task_after_assignment']
    if any(base.raw(task.get(k)) != base.raw(expected.get(k)) for k in TASK_FIELDS.split(',')):
        raise base.Stop('SCTASK mudou após falha local; retomada requer conferência manual.')


def preview(client, config, numbers, quiet=False):
    emit = (lambda *args, **kwargs: None) if quiet else print
    scope = None
    if config.get('selection_marker'):
        user_id = resolve_user(client, config)
        tag_id = tags.resolve_tag(client, config['selection_marker'], config.get('selection_tag_ids', {}).get(config['selection_marker']), config.get('selection_tag_references', {}).get(config['selection_marker']))
        scope = dict(user_id=user_id, tag_id=tag_id, tables=['incident'] if config.get('selection_type') == 'inc' else (['sc_req_item'] if config.get('selection_type') == 'ritm' else ['incident', 'sc_req_item']))
        numbers = tags.select(client, user_id, tag_id, config['max_incidents'], tables=scope['tables'])
    if config.get('selection_type') == 'inc' and any(not n.startswith('INC') for n in numbers):
        raise base.Stop('Prévia INC contém outro tipo de chamado. Execute prever --tipo inc novamente.')
    if config.get('selection_type') == 'ritm' and any(not n.startswith('RITM') for n in numbers):
        raise base.Stop('Prévia RITM contém outro tipo; execute prever --tipo ritm.')
    payloads = batch_targets(client, config, numbers)
    ledger = base.read_json(LEDGER) if LEDGER.exists() else {}
    items, skipped, task_targets = [], [], {}
    for number in numbers:
        row = record(client, number)
        previous = ledger.get(key(config, row))
        if previous and not resumable_local_save(previous):
            skipped.append({'number':number, 'status':ledger[key(config, row)]['status']})
            continue
        if previous:
            verify_resume_task(client, row, previous)
        eligible(row)
        if scope:
            tags.revalidate(client, row, scope)
        if table_for(number) == 'sc_req_item':
            task_targets[number] = linked_task(client, row)
        items.append(row)
    plan = dict(created_at=datetime.now(timezone.utc).isoformat(), config_hash=base.digest(config),
                schema_version=5, scope=scope, numbers=numbers, payloads=payloads, items=items, skipped=skipped,
                task_targets=task_targets)
    base.save_json(PLAN, plan)
    export_path = PLAN.parent / 'chamados_identificados.txt'
    export_path.write_text(''.join(number + '\n' for number in numbers), encoding='utf-8')
    emit('Lista completa identificada: saida/chamados_identificados.txt (inclui itens com tentativa anterior).')
    emit(f'{len(items)} chamados preparados; {len(skipped)} com tentativa anterior (consulte o diário).')
    emit(', '.join(base.raw(r['number']) for r in items))
    emit('Comentário público:\n' + config['comment'])
    emit('Destinos: INC = Resolvido(a); SCTASK vinculada à RITM = Encerrado concluído.')
    emit(f'Prévia: saida/{PLAN.name}. Nenhum chamado alterado.')

    return plan


def confirm_ritm(client, number, ident, max_wait_seconds=30):
    deadline = time.monotonic() + max_wait_seconds
    while True:
        rows = client.rows('sc_req_item', 'sys_id=' + base.sys_id(ident),
                           'sys_id,number,state,active,closed_at', 2)
        if len(rows) != 1 or base.raw(rows[0].get('sys_id')) != ident or base.raw(rows[0].get('number')) != number:
            raise base.Stop('Identificação da RITM não confirmada após encerrar SCTASK.')
        row = rows[0]
        if base.raw(row.get('state')) == '3' and base.raw(row.get('active')) in ('false','0') and base.raw(row.get('closed_at')):
            return row
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise base.Stop('SCTASK encerrada / RITM não confirmada após 30 segundos.')
        time.sleep(min(2, remaining))


def apply(client, config, numbers, quiet=False):
    emit = (lambda *args, **kwargs: None) if quiet else print
    plan = base.read_json(PLAN)
    if plan.get('schema_version') != 5:
        raise base.Stop('Prévia antiga. Execute prever novamente.')
    if config.get('selection_marker'):
        if config['selection_marker'] not in config.get('resolution_confirmed_markers', []):
            raise base.Stop('Confirme o texto e os dados de resolução para o marcador antes de aplicar.')
        scope = dict(user_id=resolve_user(client, config), tag_id=tags.resolve_tag(client, config['selection_marker'], config.get('selection_tag_ids', {}).get(config['selection_marker']), config.get('selection_tag_references', {}).get(config['selection_marker'])), tables=['incident'] if config.get('selection_type') == 'inc' else (['sc_req_item'] if config.get('selection_type') == 'ritm' else ['incident', 'sc_req_item']))
        if scope != plan.get('scope'):
            raise base.Stop('Responsável ou marcador difere da prévia.')
        numbers = plan['numbers']
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(plan['created_at'])).total_seconds()
    if not 0 <= age <= config['plan_max_age_minutes'] * 60 or plan['config_hash'] != base.digest(config) or numbers != plan['numbers']:
        raise base.Stop('Prévia expirada, lista ou configuração alterada. Execute prever.')
    payloads = batch_targets(client, config, numbers)
    if payloads != plan['payloads']:
        raise base.Stop('Referência ou responsável mudou. Execute prever.')
    ledger = base.read_json(LEDGER) if LEDGER.exists() else {}
    pending = [r for r in plan['items'] if key(config, r) not in ledger or resumable_local_save(ledger[key(config, r)])]
    if not pending:
        emit('Nenhuma resolução pendente. Confira tentativas anteriores no diário.')
        return
    emit('Resolver: ' + ', '.join(base.raw(r['number']) for r in pending))
    emit('INC: Resolvido(a). SCTASK vinculada à RITM: Encerrado concluído.')
    emit('Comentário público:\n' + config['comment'])
    phrase = f'RESOLVER {len(pending)}'
    if input(f'Digite {phrase} para executar: ').strip() != phrase:
        raise base.Stop('Cancelado antes das escritas.')
    for old in pending:
        number = base.raw(old['number'])
        table = table_for(number)
        payload = payloads[table]
        current = record(client, number)
        eligible(current)
        if plan.get('scope'):
            tags.revalidate(client, current, plan['scope'])
        if any(base.raw(current[k]) != base.raw(old[k]) for k in fields_for(number).split(',')):
            raise base.Stop(f'{number}: mudou desde a prévia; gere outra prévia.')
        task = None
        if table == 'sc_req_item':
            task = linked_task(client, current)
            expected = plan.get('task_targets', {}).get(number, {})
            if any(base.raw(task.get(k)) != base.raw(expected.get(k)) for k in TASK_FIELDS.split(',')):
                raise base.Stop(f'{number}: SCTASK mudou desde a prévia; gere outra prévia.')
        entry = dict(table=table, number=number, before=current, payload=payload, status='started',
                     started_at=datetime.now(timezone.utc).isoformat())
        if task:
            entry['task_before'] = task
            entry['catalog_item'] = current.get('cat_item')
            entry['ritm_flow_version'] = 1
        previous = ledger.get(key(config, current))
        if previous:
            if not resumable_local_save(previous):
                raise base.Stop('Tentativa anterior não permite retomada.')
            verify_resume_task(client, current, previous)
            entry['previous_attempt'] = previous
        ledger[key(config, current)] = entry
        base.save_json(LEDGER, ledger)
        try:
            parent_payload = payload
            if task:
                task_payload = dict(payload)
                if base.raw(task['assigned_to']) != payload['assigned_to']:
                    entry['stage'] = 'assigning_task'
                    base.save_json(LEDGER, ledger)
                    client.request('PATCH', 'sc_task', record_id=base.raw(task['sys_id']),
                                   body={'assigned_to':payload['assigned_to']})
                    assigned = linked_task(client, current)
                    entry['task_after_assignment'] = assigned
                    if (base.raw(assigned['sys_id']) != base.raw(task['sys_id']) or
                            base.raw(assigned['assigned_to']) != payload['assigned_to']):
                        raise base.Stop(f'{number}: atribuição da SCTASK não confirmada; encerramento não enviado.')
                entry.update(task_payload=task_payload, stage='sending_task')
                base.save_json(LEDGER, ledger)
                client.request('PATCH', 'sc_task', record_id=base.raw(task['sys_id']), body=task_payload)
                readback = client.rows('sc_task', 'sys_id=' + base.raw(task['sys_id']), TASK_FIELDS, 2)
                if len(readback) != 1:
                    raise base.Stop(f'{number}: não foi possível conferir a SCTASK após envio.')
                task_after = readback[0]
                entry['task_after'] = task_after
                if (base.raw(task_after['sys_id']) != base.raw(task['sys_id']) or
                        base.raw(task_after.get('request_item')) != base.raw(current['sys_id']) or
                        any(base.raw(task_after.get(k)) != v for k,v in task_payload.items() if k != 'comments')):
                    raise base.Stop(f'{number}: campos da SCTASK não persistiram como esperado: ' + ', '.join(k for k,v in task_payload.items() if k != 'comments' and base.raw(task_after.get(k)) != v))
                entry['stage'] = 'task_fields_verified_comment_pending'
                after = task_after
            else:
                client.request('PATCH', table, record_id=base.raw(current['sys_id']), body=parent_payload)
                after = record(client, number)
            entry['after'] = after
            for field, value in parent_payload.items():
                if field != 'comments' and base.raw(after[field]) != value:
                    raise base.Stop(f'{number}: {field} não persistiu como esperado.')
            if task:
                entry['stage'] = 'waiting_ritm'
                base.save_json(LEDGER, ledger)
                entry['ritm_after'] = confirm_ritm(client, number, base.raw(current['sys_id']))
            entry.update(status='fields_verified_comment_pending', after=after)
            if base.normalized(config.get('selection_marker','')) == 'venda ativa':
                from historico_venda_ativa import read_resolution_date
                entry['resolution_date'] = read_resolution_date(client,number,base.raw(current['sys_id']))
            base.save_json(LEDGER, ledger)
            emit(f'{number}: resolução conferida; confira o comentário na Atividade.')
        except Exception as exc:
            entry.update(status='uncertain', error=str(exc)[:1500])
            if task:
                entry['fields_not_confirmed'] = [k for k,v in payload.items() if k != 'comments' and base.raw(entry.get('task_after', {}).get(k)) != v]
                entry['api_error'] = getattr(exc, 'response_text', '')
                entry['message'] = ('SCTASK encerrada / RITM não confirmada; ' + str(exc)) if entry.get('stage') == 'waiting_ritm' else (str(exc) + (' | ' + entry['api_error'] if entry['api_error'] else ''))
            base.save_json(LEDGER, ledger)
            raise base.Stop(f'{number}: resultado parcial/incerto; ' + (f"item de catálogo: {base.display(current.get('cat_item'))}; {entry.get('message', str(exc))}. " if task else '') + 'Consulte resolucao_execution.json. Sem reenvio automático.') from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prever', 'aplicar'])
    parser.add_argument('--marcador', help='Seleciona automaticamente INC e RITM da sua carteira com este marcador exato')
    parser.add_argument("--visivel", action="store_true", help="Conecta ao Brave aberto manualmente na porta 9222 (padrão).")
    args = parser.parse_args()
    connection, config, numbers = settings(args.marcador)
    with base.execution_lock(), base.connected(connection) as client:
        (preview if args.command == 'prever' else apply)(client, config, numbers)


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    try:
        main()
    except (base.Stop, ValueError, KeyError, OSError) as exc:
        print('Interrompido: ' + str(exc), file=sys.stderr)
        raise SystemExit(2)
    except KeyboardInterrupt:
        print('Interrompido. Confira saida/resolucao_execution.json antes de retomar.')
        raise SystemExit(130)
