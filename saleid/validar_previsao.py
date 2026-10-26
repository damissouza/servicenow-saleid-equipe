"""Dependencia de testes: comparacao pura copiada do validador existente, sem navegador."""
FIELDS = ('chamado','franquia','matriculas','cpfs','data_abertura')

def differences(expected, actual):
    left = {r['chamado']:r for r in expected}
    right = {r['chamado']:r for r in actual}
    rows = []
    for number in dict.fromkeys(list(left)+list(right)):
        a,b=left.get(number,{}),right.get(number,{})
        if not a or not b or a.get('_worker_error') or b.get('_worker_error'):
            rows.append(dict(chamado=number,campo='falha de leitura',esperado=a.get('resultado','Ausente'),obtido=b.get('resultado','Ausente')))
            continue
        for field in FIELDS:
            default = [] if field == 'matriculas' else {} if field == 'cpfs' else ''
            if a.get(field,default) != b.get(field,default):
                rows.append(dict(chamado=number,campo=field,esperado=a.get(field,default),obtido=b.get(field,default)))
        if not a.get('resultado','').startswith('Conferido') or not b.get('resultado','').startswith('Conferido'):
            rows.append(dict(chamado=number,campo='leitura incompleta',esperado=a.get('resultado','Ausente'),obtido=b.get('resultado','Ausente')))
    return rows
