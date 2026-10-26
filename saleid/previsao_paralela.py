"""Três leitores independentes; retries somente de leitura e por chamado."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import bulk_update as base
import inspecionar_matriculas as inspector


def signature(rows):
    return {r['chamado']:(r.get('franquia',''), tuple(r.get('matriculas',[])),
                          r.get('cpfs',{}), r.get('data_abertura',''), r.get('resultado','')) for r in rows}


def inspect_parallel(client, connection, numbers, fields, on_result, controlled=True):
    navigation_lock = Lock()
    source_page = getattr(client.page, 'page', client.page)
    source_url = source_page.url
    if connection.get('connection_mode', 'cdp') != 'cdp':
        raise base.Stop('Três trabalhadores exigem conexão CDP; use --workers 1 neste modo.')
    if any(n.startswith('INC') for n in numbers) and source_page.locator('button[aria-label^="Fechar guia "]').count() > 5:
        raise base.Stop('Reserve três guias para a leitura paralela: deixe no máximo cinco guias de chamados abertas ou use --workers 1.')

    def worker(number):
        attempts = []
        for attempt in (1, 2):
            try:
                with base.connected(connection, prompt=False, source_url=source_url) as own_client:
                    rows = inspector.inspect(own_client, connection, [number], fields, quiet=True,
                        include_ritm=True, enrich=True, export_results=False, navigation_lock=navigation_lock)
                    if len(rows) != 1:
                        raise base.Stop('Inspeção não retornou o chamado solicitado.')
                    row = rows[0]
                    if row.get('_stop_batch') or row.get('resultado','').startswith('RITM: '):
                        raise base.Stop(row.get('resultado','Falha de leitura'))
                    attempts.append(dict(tentativa=attempt,status='leitura_concluida'))
                    row['_read_attempts'] = attempts
                    return row
            except Exception as exc:
                message = str(exc)[:1000]
                attempts.append(dict(tentativa=attempt,status='erro',erro=message))
                print(f'{number}: falha de leitura {attempt}/2; ' +
                      ('repetindo somente este chamado.' if attempt == 1 else 'registrado; demais chamados continuam.'), flush=True)
                if any(word in message.lower() for word in ('sessão', 'token', 'login', 'http 401')):
                    print(f'{number}: sessão/permissão indisponível; confira login/MFA com --visivel.', flush=True)
        return dict(chamado=number,matricula='',matriculas=[],franquia='',cpfs={},data_abertura='',
                    resultado='Falha após duas tentativas: ' + attempts[-1]['erro'],
                    _worker_error=True,_read_attempts=attempts)

    def batch(selected):
        found = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(worker, number) for number in selected]
            for future in as_completed(futures):
                row = future.result()
                found[row['chamado']] = row
                on_result(row)
        return found

    sample = numbers[:3] if controlled else []
    baseline = []
    if sample:
        print(f'Teste controlado: comparar leitura sequencial e paralela de {len(sample)} chamados.', flush=True)
        baseline = inspector.inspect(client, connection, sample, fields, quiet=True,
            include_ritm=True, enrich=True, export_results=False,
            on_result=lambda row: print('Teste sequencial: ' + row['chamado'] + ': ' + row.get('resultado','não conferido'), flush=True))
    result = batch(sample)
    mismatch = bool(sample) and signature(baseline) != signature(list(result.values()))
    if sample and not mismatch:
        print('Teste controlado aprovado: franquia, matrículas, CPF, abertura e conferência iguais.', flush=True)
    result.update(batch(numbers[len(sample):]))
    if mismatch:
        raise base.Stop('Teste controlado divergiu; resultados preservados. Gere nova prévia antes de aplicar.')
    return [result[number] for number in numbers]
