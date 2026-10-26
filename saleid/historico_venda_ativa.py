"""Histórico local de aplicações confirmadas de Venda Ativa; nunca escreve no ServiceNow."""
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re
import tempfile
import time
import bulk_update as base
from dados_previsao import render_report

NAME = 'historico_venda_ativa'
BACKUP = re.compile(r'^historico_venda_ativa_\d{8}T\d{12}Z\.json$')
FIELDS = ('chamado','matricula','franquia','cpf','data_abertura','aplicado_em','entry_key','sys_id')
PENDING = NAME+'_pendente.json'


def parse_reference_table(text):
    """Tabela colada do Excel; nenhum campo é convertido para número."""
    result={}
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError('Cole a tabela com as quatro colunas.')
    for index,line in enumerate(lines,1):
        cells=[value.strip() for value in line.split('\t')]
        if len(cells)!=4:
            raise ValueError(f'Linha {index}: use quatro colunas separadas por tabulação, copiadas da planilha.')
        if index==1 and [value.upper() for value in cells]==['NOME_FANTASIA','MATRICULA','CPF','UC']:
            continue
        franchise,registration,cpf,uc=cells
        registration=registration.upper()
        if not all(cells) or not re.fullmatch(r'[A-Z0-9]+',registration):
            raise ValueError(f'Linha {index}: campo vazio ou matrícula inválida.')
        if not re.fullmatch(r'(?:\d{11}|\d{3}\.\d{3}\.\d{3}-\d{2})',cpf):
            raise ValueError(f'Linha {index}: CPF deve ter 11 dígitos, com ou sem pontuação.')
        row=dict(franquia=franchise,matricula=registration,cpf=cpf,uc=uc)
        if registration in result and result[registration]!=row:
            raise ValueError(f'Matrícula {registration} com dados conflitantes na tabela.')
        result[registration]=row
    if not result:
        raise ValueError('Tabela sem linhas de dados.')
    return result


def review_pending(root,*,output_dir=None,favicon='favicon.ico',input_fn=None):
    """Revisa apenas os dados locais; permite retomar sem reenviar ao ServiceNow."""
    out=output_dir if output_dir is not None else root/'saida'
    path=out/PENDING
    pending=base.read_json(path)
    data=validate(pending['data'])
    if pending['base_digest']!=base.digest(load(out)):
        raise base.Stop('O histórico mudou após preparar a revisão. Não foi sobrescrito; confira a pendência local.')
    keys={tuple(key) for key in pending['keys']}
    rows=[r for r in data['rows'] if (r['chamado'],r['matricula']) in keys]
    if not rows or len(rows)!=len(keys):
        raise base.Stop('Lista de revisão inválida; histórico preservado.')
    read=input if input_fn is None else input_fn
    def ask(prompt):
        try:
            value=read(prompt).strip()
        except (EOFError,KeyboardInterrupt):
            raise base.Stop('Revisão interrompida; histórico não gravado. Retome com revisar_historico.py.') from None
        if value.upper()=='CANCELAR':
            raise base.Stop('Revisão cancelada; histórico não gravado. Retome com revisar_historico.py.')
        return value
    print('\nOs chamados já foram aplicados. Agora cole a tabela para completar o histórico.',flush=True)
    for row in rows:
        print(f"{row['chamado']} | Matrícula: {row['matricula'] or '—'} | Abertura: {row['data_abertura'] or '—'} | Resolução: {row.get('data_resolucao') or '—'}",flush=True)
    deferred=[row for row in rows if not row['matricula']]
    rows=[row for row in rows if row['matricula']]
    if deferred:
        print('Sem matrícula, preservados como pendentes: '+', '.join(r['chamado'] for r in deferred)+'. Os demais seguem para a tabela.',flush=True)
    if not rows:
        raise base.Stop('Todos os registros pendentes estão sem matrícula. Histórico preservado; confira esses chamados sem repetir a aplicação.')
    needed={r['matricula'] for r in rows}
    pasted=pending.get('pasted_reference',{})
    while True:
        print('Cole NOME_FANTASIA\tMATRICULA\tCPF\tUC e as linhas. Termine com FIM em uma linha separada. CANCELAR adia.',flush=True)
        lines=[]
        while True:
            line=ask('')
            if line.upper()=='FIM':
                break
            if line:
                lines.append(line)
        try:
            incoming=parse_reference_table('\n'.join(lines)) if lines else {}
            pasted.update(incoming)
            missing=sorted(needed-set(pasted))
            pending['pasted_reference']=pasted
            base.save_json(path,pending)
            if missing:
                print('Ainda faltam na tabela: '+', '.join(missing)+'. Cole as linhas faltantes.',flush=True)
                continue
            if not pasted:
                raise ValueError('Cole os dados do lote.')
            break
        except ValueError as exc:
            print('Tabela não aceita: '+str(exc),flush=True)
    extra=set(pasted)-needed
    if extra:
        print(f'{len(extra)} matrícula(s) fora do lote ignorada(s); não serão adicionadas ao histórico.',flush=True)
    for row in rows:
        reference=pasted[row['matricula']]
        row.update({field:reference[field] for field in ('franquia','cpf','uc')})
        base.save_json(path,pending)
    print('\nDados associados por matrícula para gravação:',flush=True)
    for row in rows:
        print(' | '.join(str(row.get(k,'') or '—') for k in ('chamado','franquia','matricula','cpf','uc','data_abertura','data_resolucao')),flush=True)
    if ask('Digite GRAVAR para atualizar somente o histórico local: ')!='GRAVAR':
        raise base.Stop('Gravação não confirmada; retome com revisar_historico.py. Não repita a aplicação no ServiceNow.')
    deferred_keys={(r['chamado'],r['matricula']) for r in deferred}
    # Não publicar campos incompletos nem perder os itens que precisam de conferência.
    existing=load(out)
    original_rows={(r['chamado'],r['matricula']):r for r in existing['rows']}
    published=[]
    for row in data['rows']:
        key=(row['chamado'],row['matricula'])
        if key not in deferred_keys:
            published.append(row)
        elif key in original_rows:
            published.append(original_rows[key])
    write_data(root,dict(data,rows=published),out,favicon=favicon)
    if deferred:
        pending['keys']=[list(key) for key in deferred_keys]
        pending['base_digest']=base.digest(load(out))
        base.save_json(path,pending)
        print('Histórico dos demais gravado; pendência sem matrícula preservada: '+', '.join(r['chamado'] for r in deferred),flush=True)
    else:
        path.unlink()
    return len(rows)


def format_resolution_date(raw):
    if not raw:
        return ''
    date=datetime.strptime(raw,'%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
    return date.astimezone(timezone(timedelta(hours=-3))).strftime('%d-%m-%Y %H:%M:%S')


def read_resolution_date(client,number,ident,*,max_wait_seconds=30):
    """Aguarda a atualização assíncrona da data, repetindo somente GET."""
    deadline=time.monotonic()+max_wait_seconds
    attempts=0
    while True:
        result=_read_resolution_date_once(client,number,ident)
        attempts+=1
        result['read_attempts']=attempts
        pending=result.get('error')=='Chamado ainda não está resolvido/encerrado; data não confirmada.'
        empty=not result.get('error') and not result.get('value')
        remaining=deadline-time.monotonic()
        if not (pending or empty) or remaining<=0:
            return result
        if attempts==1:
            print(number+': aguardando a data real de resolução/encerramento no ServiceNow...',flush=True)
        time.sleep(min(2,remaining))


def _read_resolution_date_once(client,number,ident):
    """GET do chamado original; nunca substituir pela data da tarefa ou do lote."""
    table='incident' if number.startswith('INC') else 'sc_req_item'
    field='resolved_at' if table=='incident' else 'closed_at'
    result=dict(table=table,field=field,value='',data_resolucao='')
    try:
        rows=client.rows(table,'sys_id='+base.sys_id(ident),'sys_id,number,state,opened_at,'+field,2)
        if len(rows)!=1 or base.raw(rows[0].get('number'))!=number or base.raw(rows[0].get('sys_id'))!=ident:
            raise ValueError('Identificação da data não conferida.')
        row=rows[0]
        if field not in row:
            raise ValueError('Campo de data não retornado; confira a permissão de leitura.')
        if base.raw(row.get('state')) not in (('6','7') if table=='incident' else ('3',)):
            raise ValueError('Chamado ainda não está resolvido/encerrado; data não confirmada.')
        raw=base.raw(row[field])
        result.update(value=raw,data_resolucao=format_resolution_date(raw),opened_at=base.raw(row.get('opened_at')))
        if raw and result['opened_at'] and raw < result['opened_at']:
            result['warning']='Data de resolução anterior à abertura.'
    except Exception as exc:
        result['error']=str(exc)
    return result


def opening_order(row):
    value=row.get('data_abertura','')
    return datetime.strptime(value,'%d-%m-%Y %H:%M:%S') if value else datetime.min


def resolution_order(row):
    value=row.get('data_resolucao','')
    date=datetime.strptime(value,'%d-%m-%Y %H:%M:%S') if value else datetime.min
    return not bool(value),date,opening_order(row),row['chamado'],row['matricula']


def validate(data):
    if not isinstance(data,dict) or data.get('schema_version') != 1 or data.get('marcador') != 'Venda Ativa' or not isinstance(data.get('rows'),list):
        raise ValueError('Estrutura do histórico inválida.')
    seen=set()
    for row in data['rows']:
        if not isinstance(row,dict) or any(not isinstance(row.get(k),str) for k in FIELDS):
            raise ValueError('Registro do histórico inválido.')
        if not re.fullmatch(r'(?:INC|RITM)\d{7}',row['chamado']) or not re.fullmatch(r'[0-9a-f]{32}',row['sys_id']):
            raise ValueError('Identificação do chamado inválida.')
        stamp=datetime.fromisoformat(row['aplicado_em'])
        if stamp.tzinfo is None:
            raise ValueError('Horário de aplicação sem fuso.')
        opening_order(row)
        for field in ('uc','data_atribuicao','data_resolucao'):
            if field in row and not isinstance(row[field],str):
                raise ValueError('CPF, UC e datas devem permanecer como texto.')
        for field in ('data_atribuicao','data_resolucao'):
            if row.get(field):
                datetime.strptime(row[field],'%d-%m-%Y %H:%M:%S')
        key=(row['chamado'],row['matricula'])
        if key in seen:
            raise ValueError('Registro duplicado no histórico.')
        seen.add(key)
    return data


def load(out):
    path=out/(NAME+'.json')
    if not path.exists():
        return dict(schema_version=1,marcador='Venda Ativa',rows=[])
    try:
        return validate(json.loads(path.read_text(encoding='utf-8')))
    except (OSError,ValueError,TypeError) as exc:
        raise base.Stop('Histórico de Venda Ativa inválido ou ilegível; atualização interrompida, sem criar uma base vazia: '+str(exc)) from exc


def selected(config,plan):
    return (base.normalized(config.get('selection_marker','')) == 'venda ativa' and
            plan.get('orchestrator_version') == 1 and not plan.get('inspection_error') and
            plan.get('config_hash') == base.digest(config) and bool((plan.get('scope') or {}).get('tag_id')))


def confirmed_rows(config,plan,before,after):
    if not selected(config,plan):
        return []
    items={base.raw(r['sys_id']):base.raw(r['number']) for r in plan.get('items',[])}
    inspection={r['chamado']:r for r in plan.get('inspection',[])}
    stamp=datetime.now(timezone.utc).isoformat()
    rows=[]
    for key,entry in after.items():
        if entry == before.get(key) or entry.get('status') != 'fields_verified_comment_pending':
            continue
        ident=base.raw(entry.get('before',{}).get('sys_id'));number=items.get(ident)
        if not number or entry.get('number') != number or number not in inspection:
            continue
        record=inspection[number]
        if record.get('_worker_error'):
            continue
        for registration in record.get('matriculas',[]) or ['']:
            rows.append(dict(chamado=number,matricula=registration,franquia=record.get('franquia',''),
                cpf=record.get('cpfs',{}).get(registration,''),data_abertura=record.get('data_abertura',''),
                uc='',data_atribuicao=record.get('data_atribuicao',''),data_resolucao=entry.get('resolution_date',{}).get('data_resolucao',''),
                resolution_date=entry.get('resolution_date',{}),aplicado_em=stamp,entry_key=key,sys_id=ident))
    return rows


def collect_assignments(client, rows, out):
    """Read after resolution; never infer dates or repeat ServiceNow writes."""
    from atividade_atribuicoes import ActivityReader
    try:
        page = getattr(client.page, 'page', client.page)
        with ActivityReader(page.context, out/'.atribuicoes', client.origin) as reader:
            dates = {}
            for row in rows:
                number = row['chamado']
                if number not in dates:
                    opening, resolution = row.get('data_abertura'), row.get('data_resolucao')
                    dates[number] = reader.read('incident' if number.startswith('INC') else 'sc_req_item',
                        row['sys_id'], number, opening, resolution) if opening and resolution else None
                    print(number + (': atribuicao confirmada.' if dates[number] else
                        ': atribuicao pendente; retome pelo coletor somente leitura.'), flush=True)
                if dates[number]:
                    row['data_atribuicao'] = dates[number]
    except (Exception, KeyboardInterrupt) as exc:
        print('Leitura da atribuicao interrompida; resolucoes preservadas: ' + str(exc), flush=True)


def update(root,config,plan,before,after,*,output_dir=None,favicon='favicon.ico',review=True,client=None):
    additions=confirmed_rows(config,plan,before,after)
    if not additions:
        return 0
    out=output_dir if output_dir is not None else root/'saida'
    original=load(out)
    if client is not None:
        collect_assignments(client, additions, out)
    reference_path=root/'saida/franquias_referencia.json'
    references={}
    if reference_path.exists():
        reference=json.loads(reference_path.read_text(encoding='utf-8'))
        for item in reference['rows']:
            if item['matricula'] in references:
                raise ValueError('Matrícula duplicada na tabela de referência.')
            if any(not isinstance(item.get(k),str) for k in ('matricula','franquia','cpf','uc')):
                raise ValueError('A tabela de referência deve guardar CPF e UC como texto.')
            references[item['matricula']]=item
    indexed={(r['chamado'],r['matricula']):dict(r) for r in original['rows']}
    for row in additions:
        reference=references.get(row['matricula'])
        if reference:
            row.update({k:reference[k] for k in ('franquia','cpf','uc')})
        key=(row['chamado'],row['matricula'])
        previous=indexed.get(key,{})
        # Não apagar dados preenchidos com vazios ou placeholders de outra execução.
        merged=dict(previous)
        for field,value in row.items():
            if field in ('franquia','cpf','uc','data_abertura','data_atribuicao') and value in ('','—') and previous.get(field) not in (None,'','—'):
                continue
            merged[field]=value
        indexed[key]=merged
    data=dict(schema_version=1,marcador='Venda Ativa',rows=sorted(indexed.values(),
        key=resolution_order))
    if review:
        pending=out/PENDING
        if pending.exists():
            raise base.Stop('Há revisão anterior pendente; execute revisar_historico.py antes de outro lote.')
        base.save_json(pending,dict(base_digest=base.digest(original),data=data,
            keys=[list(key) for key in {(r['chamado'],r['matricula']) for r in additions}]))
        written=review_pending(root,output_dir=out,favicon=favicon)
    else:
        write_data(root,data,out,favicon=favicon)
        written=len(additions)
    missing=sorted({r['chamado'] for r in additions if not r.get('data_resolucao')})
    if missing:
        print('Histórico: sem data de resolução confirmada: '+', '.join(missing),flush=True)
    return written


def write_data(root,data,out,*,favicon='favicon.ico'):
    """Gravação local com backup; usada também na migração autorizada."""
    load(out)
    data=dict(data,rows=sorted(data['rows'],key=resolution_order))
    validate(data)
    out.mkdir(parents=True,exist_ok=True)
    records=[dict(chamado=r['chamado'],franquia=r['franquia'],matriculas=[r['matricula']] if r['matricula'] else [],
                  cpfs={r['matricula']:r['cpf']},uc=r.get('uc',''),data_atribuicao=r.get('data_atribuicao',''),data_resolucao=r.get('data_resolucao',''),data_abertura=r['data_abertura']) for r in data['rows']]
    with tempfile.TemporaryDirectory(prefix='.historico-stage-',dir=out) as directory:
        stage=Path(directory)
        render_report(root,records,basename=NAME,title='Histórico de Venda Ativa',output_dir=stage,favicon=favicon,history_columns=True)
        pending=stage/(NAME+'.json')
        with pending.open('w',encoding='utf-8') as file:
            json.dump(data,file,ensure_ascii=False,indent=2);file.flush();os.fsync(file.fileno())
        validate(json.loads(pending.read_text(encoding='utf-8')))
        destination=out/(NAME+'.json')
        if destination.exists():
            backups=out.parent/'backups'/NAME;backups.mkdir(parents=True,exist_ok=True)
            backup=backups/(NAME+'_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
            with backup.open('xb') as file:
                file.write(destination.read_bytes());file.flush();os.fsync(file.fileno())
            validate(json.loads(backup.read_text(encoding='utf-8')))
        os.replace(pending,destination)
        for extension in ('css','html'):
            os.replace(stage/(NAME+'.'+extension),out/(NAME+'.'+extension))
    backup_dir=out.parent/'backups'/NAME
    if backup_dir.exists():
        owned=sorted(p for p in backup_dir.iterdir() if p.is_file() and BACKUP.fullmatch(p.name))
        for path in owned[:-30]:
            path.unlink()
