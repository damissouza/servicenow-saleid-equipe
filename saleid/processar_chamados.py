"""Entrada única: prévia com matrículas e aplicação das regras existentes."""
import argparse
from datetime import datetime, timezone
import html
from pathlib import Path
import sys
import publicar_site as site

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import bulk_update as base
import resolver_incidentes as resolver
import inspecionar_matriculas as inspector


def report(plan, phase, error='', before=None, after=None):
    before, after = before or {}, after or {}
    inspection = {r['chamado']:r for r in plan.get('inspection', [])}
    skipped = {r['number']:r['status'] for r in plan.get('skipped', [])}
    items = {base.raw(r['number']):r for r in plan.get('items', [])}
    rows = []
    verified = uncertain = 0
    for number in plan['numbers']:
        data = inspection.get(number, {})
        task = plan.get('task_targets', {}).get(number)
        status = 'Preparado' if number in items else 'Tentativa anterior: ' + skipped.get(number, 'não preparada')
        if phase == 'aplicar' and number in items:
            ident = base.raw(items[number]['sys_id'])
            entries = [(k,v) for k,v in after.items() if base.raw(v.get('before', {}).get('sys_id')) == ident]
            new = [v for k,v in entries if k not in before]
            if new:
                state = new[-1]['status']
                if state == 'fields_verified_comment_pending':
                    status = 'Campos confirmados; comentário pendente de conferência'
                    verified += 1
                else:
                    status = 'Resultado incerto: ' + state
                    uncertain += 1
            elif entries:
                status = 'Tentativa anterior; não reenviado'
            else:
                status = 'Não executado'
        rows.append(dict(chamado=number, matricula=data.get('matricula',''),
                         destino_resposta=base.raw(task['number']) if task else number,
                         matriculas=data.get('matriculas', [data['matricula']] if data.get('matricula') else []),
                         franquia=data.get('franquia',''),
                         leitura=data.get('resultado','Não inspecionado; conferir manualmente'), resultado=status))
    result = dict(phase=phase, generated_at=datetime.now(timezone.utc).isoformat(),
                  total=len(rows), matriculas_identificadas=sum(len(r['matriculas']) for r in rows),
                  preparados=len(items), resolucoes_confirmadas=verified, incertos=uncertain,
                  error=error, rows=rows)
    out = ROOT / 'saida'
    base.save_json(out/'resumo_chamados.json', result)
    escape = lambda value: html.escape(str(value))
    table = ''.join('<tr>'+''.join('<td>'+escape(r[k] or '—')+'</td>' for k in ('chamado','matricula','franquia','leitura','resultado'))+'</tr>' for r in rows)
    destinations = ''.join('<li>'+escape(r['chamado'])+' → '+escape(r['destino_resposta'])+'</li>' for r in rows if r['destino_resposta'] != r['chamado'])
    content = '<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Resumo de chamados</title><style>body{font:15px system-ui;background:#f4f7f8;color:#183039;margin:0;padding:32px}main{max-width:1200px;margin:auto;background:white;padding:28px;border-radius:12px}h1{margin-top:0}.cards{display:flex;gap:24px;flex-wrap:wrap;margin:24px 0}.card{background:#edf6f2;padding:18px;border-radius:8px}strong{font-size:26px;display:block}table{border-collapse:collapse;width:100%}th,td{padding:12px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}th{background:#edf6f2}.error{background:#fff0df;padding:16px}small{color:#52666d}</style><main><h1>Resumo de chamados — '+escape(phase)+'</h1><small>'+escape(result['generated_at'])+' (UTC)</small><div class="cards"><div class="card"><strong>'+str(result['total'])+'</strong>Chamados no lote</div><div class="card"><strong>'+str(result['matriculas_identificadas'])+'</strong>Matrículas identificadas</div><div class="card"><strong>'+str(verified)+'</strong>Resoluções confirmadas nesta execução</div></div>'
    if error:
        content += '<p class="error">Interrompido: '+escape(error)+'</p>'
    if destinations:
        content += '<h2>Destino do comentário e das anotações</h2><ul>'+destinations+'</ul>'
    content += '<p>A matrícula identificada foi extraída do chamado; não comprova cadastro ou situação comercial no CTN. Valores ausentes ou ambíguos exigem conferência.</p><table><thead><tr><th>Chamado</th><th>Matrícula</th><th>Franquia</th><th>Inspeção</th><th>Processamento</th></tr></thead><tbody>'+table+'</tbody></table></main></html>'
    (out/'resumo_chamados.html').write_text(content, encoding='utf-8')
    print(f"Resumo ({phase}): {len(rows)} chamados no lote; {result['matriculas_identificadas']} matrículas identificadas.")
    if phase == 'aplicar':
        print(f'Resoluções confirmadas nesta execução: {verified}; resultados incertos: {uncertain}.')
    if phase == 'prever':
        print('Chamados:')
        for row in rows:
            print(row['chamado'])
        registrations = [registration for row in rows for registration in row['matriculas'] if registration]
        print('Matrículas:')
        print(','.join("('"+ registration.replace("'","''") +"')" for registration in registrations) or 'Nenhuma matrícula identificada.')
    else:
        for row in rows:
            print(row['chamado'] + ': ' + (row['matricula'] or 'matrícula pendente'))
    if error:
        print('Interrompido: ' + error, file=sys.stderr)
    print('HTML: saida/resumo_chamados.html')
    return result


def inspect_for_preview(client, connection, plan, workers=1):
    plan['inspection'] = []
    base.save_json(ROOT/'saida/previsao_execution.json', {'phase':'prever','rows':[]})
    error = ''
    try:
        if plan['numbers']:
            fields = base.read_json(ROOT/'config_inspecao.json')
            completed = {}
            def progress(row):
                completed[row['chamado']] = row
                state = 'conferido' if row.get('resultado','').startswith('Conferido') else 'não conferido: ' + row.get('resultado','')
                print(f"[{len(completed)}/{len(plan['numbers'])}] {row['chamado']}: {state}", flush=True)
                plan['inspection'] = [completed[n] for n in plan['numbers'] if n in completed]
                base.save_json(resolver.PLAN, plan)
                base.save_json(ROOT/'saida/previsao_execution.json', {
                    'phase':'prever','rows':plan['inspection']})
            if workers == 3:
                from previsao_paralela import inspect_parallel
                plan['inspection'] = inspect_parallel(client, connection, plan['numbers'], fields, progress)
            else:
                from previsao_sequencial import inspect_sequential
                plan['inspection'] = inspect_sequential(client, connection, plan['numbers'], fields, progress)
            if len(plan['inspection']) != len(plan['numbers']):
                raise base.Stop('Inspeção incompleta; consulte o relatório parcial antes de aplicar.')
            if any(row.get('_worker_error') for row in plan['inspection']):
                raise base.Stop('Leituras com falha registradas em saida/previsao_execution.json; demais chamados foram processados.')
    except (Exception, KeyboardInterrupt) as exc:
        error = str(exc) or 'Coleta interrompida; nenhuma resolucao enviada.'
    plan['inspection_error'] = error
    base.save_json(resolver.PLAN, plan)
    from dados_previsao import render_report
    render_report(ROOT, plan['inspection'])
    return error


def run(client, connection, config, numbers, phase, workers=1):
    if phase == 'prever':
        plan = resolver.preview(client, config, numbers, quiet=True)
        error = inspect_for_preview(client, connection, plan, workers)
        plan['orchestrator_version'] = 0 if error else 1
        base.save_json(resolver.PLAN, plan)
        report(plan, phase, error)
        return 2 if error else 0
    plan = base.read_json(resolver.PLAN)
    if plan.get('orchestrator_version') != 1:
        raise base.Stop('Execute processar_chamados.py prever para gerar a prévia com inspeção.')
    import historico_venda_ativa as history
    if history.selected(config,plan):
        history.load(ROOT/'saida')  # JSON inválido impede a atualização; nunca reiniciar uma base existente.
        if (ROOT/'saida'/history.PENDING).exists():
            raise base.Stop('Revisão do histórico pendente. Execute revisar_historico.py antes de aplicar outro lote.')
    before = base.read_json(resolver.LEDGER) if resolver.LEDGER.exists() else {}
    error = ''
    try:
        resolver.apply(client, config, numbers, quiet=True)
    except (Exception, KeyboardInterrupt) as exc:
        error = str(exc) or 'Execução interrompida pelo usuário.'
    after = base.read_json(resolver.LEDGER) if resolver.LEDGER.exists() else {}
    added = 0
    try:
        added=history.update(ROOT,config,plan,before,after,client=client)
        if added:
            print('Histórico de Venda Ativa atualizado: saida/historico_venda_ativa.html',flush=True)
    except Exception as exc:
        error=(error+' | ' if error else '')+'Falha ao atualizar o histórico local: '+str(exc)+'. As confirmações estão no diário; não repita escritas no ServiceNow para corrigir o arquivo.'
    if added:
        try:
            site.synchronize(ROOT, config)
        except site.PublicationPending as exc:
            error = (error + ' | ' if error else '') + str(exc)
    report(plan, phase, error, before, after)
    return 2 if error else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prever','aplicar'))
    parser.add_argument('--marcador')
    parser.add_argument('--tipo', choices=('inc','ritm'), help='Seleciona INC ou RITM, com prévia exclusiva por tipo.')
    parser.add_argument('--workers', type=int, choices=(1,3), default=1,
                        help='Padrão: 1 (sequencial). 3 mantém o paralelo opcional com teste controlado.')
    parser.add_argument("--visivel", action="store_true", help="Conecta ao Brave aberto manualmente na porta 9222 (padrão).")
    args = parser.parse_args()
    connection, config, numbers = resolver.settings(args.marcador)
    if args.tipo:
        config['selection_type'] = args.tipo
        numbers = [n for n in numbers if n.startswith('INC' if args.tipo == 'inc' else 'RITM')]
        resolver.PLAN = ROOT / f'saida/resolucao_preview_{args.tipo}.json'
    with base.execution_lock():
        with base.connected(connection) as client:
            return run(client, connection, config, numbers, args.command, workers=args.workers)


if __name__ == '__main__':
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf-8',errors='replace')
    try:
        raise SystemExit(main())
    except (base.Stop,OSError,ValueError,KeyError) as exc:
        print('Interrompido: '+str(exc),file=sys.stderr)
        raise SystemExit(2)
