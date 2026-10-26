"""Seleção e revalidação de INC e RITM por responsável e marcador."""
# Permite executar diretamente os scripts nas pastas por função.
import sys as _sys
from pathlib import Path as _Path
_project_root = _Path(__file__).resolve().parent
_sys.path.insert(0, str(_project_root))

import bulk_update as base
from numeros_chamados import table_for


def pages(client, table, query, fields):
    offset, seen = 0, set()
    while True:
        rows = client.request('GET', table, params={
            'sysparm_query':query + '^ORDERBYsys_id', 'sysparm_fields':fields,
            'sysparm_limit':'100', 'sysparm_offset':str(offset),
            'sysparm_display_value':'all', 'sysparm_exclude_reference_link':'true'})
        if not isinstance(rows, list):
            raise base.Stop('Resposta inesperada na seleção por marcador.')
        if not rows:
            return
        for row in rows:
            ident = base.sys_id(base.raw(row.get('sys_id')))
            if ident in seen or len(seen) >= 10000:
                raise base.Stop('Paginação repetida ou acima do limite de leitura.')
            seen.add(ident)
            yield row
        offset += len(rows)


def marker_name(value):
    return ' '.join(str(value).split()).casefold()


def resolve_tag(client, name, specified_id=None, references=None):
    name = base.safe(name)
    if references:
        matches = []
        for number in references:
            table = table_for(number)
            records = client.rows(table, 'number=' + number, 'sys_id,number', 2)
            if len(records) != 1 or base.raw(records[0].get('number')) != number:
                raise base.Stop(f'{number}: referência do marcador não encontrada.')
            record_id = base.sys_id(base.raw(records[0]['sys_id']))
            ids = set()
            for entry in pages(client, 'label_entry', 'table_key=' + record_id,
                               'sys_id,table,table_key,label'):
                if base.raw(entry.get('table_key')) != record_id or base.raw(entry.get('table')) != table:
                    continue
                label = entry.get('label')
                display_name = label.get('display_value', '') if isinstance(label, dict) else ''
                if display_name and marker_name(display_name) == marker_name(name):
                    ids.add(base.sys_id(base.raw(label)))
            if len(ids) != 1:
                raise base.Stop(f'{number}: o vínculo não retornou um único nome/ID para {name!r}. '
                                'Execute diagnosticar_marcador.py para conferir os dados acessíveis.')
            matches.append(ids)
        common = set.intersection(*matches)
        if len(common) != 1 or specified_id and specified_id not in common:
            raise base.Stop('As referências não confirmam o mesmo marcador. Nenhuma escrita realizada.')
        return common.pop()
    fields = 'sys_id,name,owner'
    query = 'sys_id=' + base.sys_id(specified_id) if specified_id else 'name=' + name
    candidates = list(pages(client, 'label', query, fields))
    rows = [r for r in candidates if marker_name(base.raw(r.get('name'))) == marker_name(name)
            and (not specified_id or base.raw(r.get('sys_id')) == specified_id)]
    if not rows and not specified_id:
        # Busca auxiliar para diagnosticar grafia e espaços; nunca seleciona por nome parcial.
        candidates = list(pages(client, 'label', 'nameLIKE' + name.split()[0], fields))
        rows = [r for r in candidates if marker_name(base.raw(r.get('name'))) == marker_name(name)]
    if len(rows) != 1:
        report = {'requested_name':name, 'specified_id':specified_id, 'matching_count':len(rows),
                  'candidates':candidates}
        base.save_json(base.ROOT / 'saida' / 'diagnostico_marcador.json', report)
        if len(rows) > 1:
            reason = f'{len(rows)} marcadores acessíveis possuem esse nome'
        else:
            reason = 'nenhum marcador compatível retornou pela API; pode ser nome diferente ou visibilidade da conta'
        raise base.Stop(f'Marcador {name!r}: {reason}. Confira saida/diagnostico_marcador.json. '
                        'Nenhum chamado foi alterado.')
    return base.sys_id(base.raw(rows[0]['sys_id']))


def linked(client, record_id, tag_id, table='incident'):
    if table not in ('incident', 'sc_req_item'):
        raise base.Stop('Tabela não permitida na seleção por marcador.')
    rows = client.rows('label_entry', f'table={table}^table_key={record_id}^label={tag_id}',
                       'sys_id,table,table_key,label', 100)
    return any(base.raw(r.get('table')) == table and base.raw(r.get('table_key')) == record_id
               and base.raw(r.get('label')) == tag_id for r in rows)


def pending_ritm(row):
    label=base.normalized(base.display(row.get('state')))
    return label.startswith('pendente') or label.startswith('pending')


def select(client, user_id, tag_id, limit, tables=None):
    numbers = []
    for table in (tables if tables is not None else ('incident', 'sc_req_item')):
        state_filter = '^stateIN1,2,3' if table == 'incident' else '^state!=3'
        for row in pages(client, table, f'assigned_to={user_id}^active=true' + state_filter,
                         'sys_id,number,assigned_to,active,state'):
            state = base.raw(row.get('state'))
            allowed = state in ('1','2','3') if table == 'incident' else bool(state) and state != '3'
            if (base.raw(row.get('assigned_to')) != user_id or base.raw(row.get('active')) not in ('true','1')
                    or not allowed):
                raise base.Stop('Consulta retornou chamado fora dos filtros solicitados.')
            if table=='sc_req_item' and pending_ritm(row):
                continue
            number = base.raw(row.get('number'))
            if table_for(number) != table:
                raise base.Stop('Número retornado não corresponde à tabela consultada.')
            if linked(client, base.raw(row['sys_id']), tag_id, table):
                numbers.append(number)
                if len(numbers) > limit:
                    raise base.Stop('Quantidade excede max_incidents; nenhuma lista parcial será executada.')
    return sorted(numbers)


def revalidate(client, row, scope):
    if base.raw(row['assigned_to']) != scope['user_id'] or not linked(client, base.raw(row['sys_id']), scope['tag_id'], table_for(base.raw(row['number']))):
        raise base.Stop(f"{base.raw(row['number'])}: responsável ou marcador mudou; interrompido antes do envio.")
