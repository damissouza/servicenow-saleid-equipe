"""Complementação local do histórico por tabela; sem navegador ou ServiceNow."""
from datetime import datetime
import re
import historico_venda_ativa as history
import bulk_update as base


def parse_table(text):
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    result={}; expected=None
    for index,line in enumerate(lines,1):
        cells=[value.strip() for value in line.split('\t')]
        if index==1 and len(cells)==4 and re.fullmatch(r'UC\s+CHAMADO',cells[-1],re.I):
            cells=cells[:3]+['UC','CHAMADO']
        # Aceita também a última separação com espaço, como no exemplo fornecido.
        if len(cells)==4:
            match=re.fullmatch(r'(\S+)\s+((?:INC|RITM)\d{7,})',cells[-1],re.I)
            if match:cells=cells[:3]+list(match.groups())
        if index==1 and [v.upper() for v in cells] in (
            ['NOME_FANTASIA','MATRICULA','CPF','UC'],
            ['NOME_FANTASIA','MATRICULA','CPF','UC','CHAMADO']):
            expected=len(cells);continue
        if len(cells) not in (4,5) or (expected and len(cells)!=expected):
            raise ValueError(f'Linha {index}: use quatro colunas, ou cinco com CHAMADO no final, separadas por tabulação.')
        expected=expected or len(cells)
        franchise,registration,cpf,uc=cells[:4]
        number=cells[4].upper() if len(cells)==5 else ''
        # Reutiliza a validação existente; não converte CPF/UC para número.
        parsed=history.parse_reference_table('\t'.join(cells[:4]))
        registration=registration.upper()
        if number and not re.fullmatch(r'(?:INC|RITM)\d{7}',number):
            raise ValueError(f'Linha {index}: CHAMADO inválido; use INC ou RITM com sete dígitos.')
        item=dict(parsed[registration],chamado=number)
        key=(number,registration)
        if key in result and result[key]!=item:
            raise ValueError(f'Linha {index}: informações conflitantes para o mesmo chamado e matrícula.')
        result[key]=item
    if not result:raise ValueError('Tabela sem linhas de dados.')
    return list(result.values())


def associate(original,pending,incoming):
    history.validate(original)
    if pending:
        history.validate(pending['data'])
        if pending['base_digest']!=base.digest(original):
            raise base.Stop('O histórico mudou após preparar a pendência; nenhum dado foi alterado.')
    known={(r['chamado'],r['matricula']):dict(r) for r in original['rows']}
    if pending:known.update({(r['chamado'],r['matricula']):dict(r) for r in pending['data']['rows']})
    updates={}; consumed=set()
    for item in incoming:
        number=item['chamado'];registration=item['matricula']
        candidates=[key for key in known if key[1]==registration and (not number or key[0]==number)]
        if not candidates and number and (number,'') in known:
            candidates=[(number,'')]
        if len(candidates)!=1:
            raise ValueError('Não há correspondência única na base para '+(number or 'matrícula informada')+'. Confira CHAMADO e MATRICULA; chamados novos exigem importação confirmada.')
        oldkey=candidates[0];newkey=(oldkey[0],registration)
        row=dict(known[oldkey],matricula=registration)
        row.update({k:item[k] for k in ('franquia','cpf','uc')})
        if newkey in updates and updates[newkey]!=row:
            raise ValueError('Dados conflitantes na associação.')
        updates[newkey]=row;consumed.add(oldkey)
    published={(r['chamado'],r['matricula']):dict(r) for r in original['rows']}
    for key in consumed:
        if key[1]=='':published.pop(key,None)
    published.update(updates)
    data=dict(original,rows=sorted(published.values(),key=history.resolution_order))
    history.validate(data)
    return data,updates,consumed


def review_table(root,*,input_fn=None):
    read=input if input_fn is None else input_fn
    out=root/'saida';original=history.load(out);path=out/history.PENDING
    pending=base.read_json(path) if path.exists() else None
    print('Cole NOME_FANTASIA\tMATRICULA\tCPF\tUC\tCHAMADO. Termine com FIM. CANCELAR preserva os arquivos.',flush=True)
    lines=[]
    while True:
        value=read('').strip()
        if value.upper()=='CANCELAR':raise base.Stop('Revisão cancelada; nenhum arquivo alterado.')
        if value.upper()=='FIM':break
        if value:lines.append(value)
    data,updates,consumed=associate(original,pending,parse_table('\n'.join(lines)))
    print('Dados associados; datas preservadas:',flush=True)
    for row in updates.values():
        print(' | '.join(row.get(k,'') or '—' for k in ('chamado','franquia','matricula','cpf','uc','data_abertura','data_resolucao')),flush=True)
    if read('Digite GRAVAR para atualizar somente o histórico local: ').strip()!='GRAVAR':
        raise base.Stop('Gravação não confirmada; nenhum arquivo alterado.')
    # Confere outra vez antes de gravar, além da trava do chamador.
    if base.digest(history.load(out))!=base.digest(original):raise base.Stop('A base mudou durante a revisão; nada foi gravado.')
    if pending:
        backup=root/'backups'/'revisao_tabela'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup.mkdir(parents=True,exist_ok=False)
        (backup/history.PENDING).write_bytes(path.read_bytes())
    history.write_data(root,data,out)
    if pending:
        remaining={tuple(k) for k in pending['keys']}-consumed-set(updates)
        if remaining:
            indexed={(r['chamado'],r['matricula']):r for r in data['rows']}
            indexed.update({(r['chamado'],r['matricula']):r for r in pending['data']['rows'] if (r['chamado'],r['matricula']) in remaining})
            pending['data']=dict(data,rows=sorted(indexed.values(),key=history.resolution_order))
            pending['keys']=[list(k) for k in sorted(remaining)]
            pending['base_digest']=base.digest(history.load(out))
            base.save_json(path,pending)
            print(f'{len(remaining)} registro(s) permanecem pendentes; não foram publicados por esta tabela.',flush=True)
        else:path.unlink()
    print(f'Histórico atualizado: {len(updates)} registro(s). Nenhum chamado alterado no ServiceNow.',flush=True)
    return len(updates)
