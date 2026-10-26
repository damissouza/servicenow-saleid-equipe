"""Leitura sequencial; uma segunda tentativa apenas para falhas técnicas do item."""
import inspecionar_matriculas as inspector


def inspect_sequential(client, connection, numbers, fields, on_result):
    results = []
    for number in numbers:
        attempts = []
        for attempt in (1, 2):
            try:
                rows = inspector.inspect(client, connection, [number], fields, quiet=True,
                    include_ritm=True, enrich=True, export_results=False)
                if len(rows) != 1 or rows[0].get('chamado') != number:
                    raise RuntimeError('Leitura não retornou o chamado solicitado de forma única.')
                row = rows[0]
                if row.get('_stop_batch') or row.get('resultado','').startswith('RITM: '):
                    raise RuntimeError(row.get('resultado','Falha de leitura'))
                attempts.append(dict(tentativa=attempt,status='leitura_concluida'))
                row['_read_attempts'] = attempts
                break
            except Exception as exc:
                message = str(exc)[:1000]
                attempts.append(dict(tentativa=attempt,status='erro',erro=message))
                print(f'{number}: falha de leitura {attempt}/2; ' +
                      ('repetindo somente este chamado.' if attempt == 1 else 'registrado; seguindo para o próximo.'),flush=True)
                if any(word in message.lower() for word in ('sessão','token','login','http 401')):
                    print(f'{number}: confira a sessão/permissão e login/MFA com --visivel.',flush=True)
                row = dict(chamado=number,matricula='',matriculas=[],franquia='',cpfs={},data_abertura='',
                    resultado='Falha após duas tentativas: '+message,_worker_error=True,_read_attempts=attempts)
        results.append(row)
        on_result(row)
    return results
