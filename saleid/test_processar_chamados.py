import copy
import io
from pathlib import Path
import tempfile
import unittest
from contextlib import contextmanager
from threading import get_ident, Lock
import time
from unittest.mock import Mock
from unittest.mock import patch
import processar_chamados as app
import dados_previsao as report_data
import previsao_paralela as parallel


class Tests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.root.mkdir(exist_ok=True)
        (self.root/'previsao_chamados.css').write_text('table {color:green}', encoding='utf-8')
        app.base.save_json(self.root/'config_inspecao.json', {})
        for obj,name,value in [(app,'ROOT',self.root),(app.resolver,'PLAN',self.root/'saida/plan.json'),
                               (app.resolver,'LEDGER',self.root/'saida/ledger.json')]:
            p = patch.object(obj,name,value); p.start(); self.addCleanup(p.stop)
        self.plan = dict(numbers=['INC0000001','RITM0000001'], items=[{'number':'INC0000001','sys_id':'a'*32},
                         {'number':'RITM0000001','sys_id':'b'*32}], skipped=[])

    def test_preview_inspects_and_does_not_apply(self):
        data = [dict(chamado='INC0000001',matricula='00123',matriculas=['00123'],franquia='<X>',resultado='Conferido'),
                dict(chamado='RITM0000001',matriculas=[],resultado='Matrícula não identificada')]
        with patch.object(app.resolver,'preview',return_value=copy.deepcopy(self.plan)), patch.object(app.inspector,'inspect',side_effect=lambda c,co,ns,f,**kw:[r for r in data if r['chamado'] in ns]) as inspect, patch.object(app.resolver,'apply') as apply, patch('sys.stdout',new_callable=io.StringIO) as stdout:
            self.assertEqual(app.run(None,{}, {}, [],'prever'),0)
            apply.assert_not_called()
            self.assertTrue(inspect.call_args.kwargs['include_ritm'])
            self.assertNotIn('Comentário público',stdout.getvalue())
        content=(self.root/'saida/resumo_chamados.html').read_text(encoding='utf-8')
        self.assertIn('00123',content)
        self.assertIn('&lt;X&gt;',content)
        result=app.base.read_json(self.root/'saida/resumo_chamados.json')
        self.assertEqual(result['total'],2)
        self.assertEqual(result['matriculas_identificadas'],1)
        self.assertIn('Matrícula não identificada',result['rows'][1]['leitura'])
        self.assertTrue((self.root/'saida/previsao_chamados.css').exists())

    def test_sequential_retry_and_failure_do_not_stop_next_item(self):
        from previsao_sequencial import inspect_sequential
        calls={}
        def read(client,connection,numbers,fields,**kwargs):
            number=numbers[0]
            calls[number]=calls.get(number,0)+1
            if number=='INC0000001' and calls[number]==1:
                raise RuntimeError('Timeout')
            if number=='INC0000002':
                return [dict(chamado=number,resultado='Falha de navegação',_stop_batch=True)]
            return [dict(chamado=number,resultado='Conferido',matriculas=['SP123000001'])]
        with patch.object(app.inspector,'inspect',side_effect=read), patch('sys.stdout',new_callable=io.StringIO):
            rows=inspect_sequential(None,{},['INC0000001','INC0000002','INC0000003'],{},Mock())
        self.assertEqual(calls,dict(INC0000001=2,INC0000002=2,INC0000003=1))
        self.assertNotIn('_worker_error',rows[0])
        self.assertTrue(rows[1]['_worker_error'])
        self.assertEqual(len(rows[0]['_read_attempts']),2)

    def test_persistent_sequential_failure_invalidates_preview_and_records_attempts(self):
        with patch.object(app.resolver,'preview',return_value=copy.deepcopy(self.plan)), patch.object(app.inspector,'inspect',side_effect=RuntimeError('Timeout')), patch('sys.stdout',new_callable=io.StringIO), patch('sys.stderr',new_callable=io.StringIO):
            self.assertEqual(app.run(None,{}, {}, [],'prever'),2)
        plan=app.base.read_json(app.resolver.PLAN)
        self.assertEqual(plan['orchestrator_version'],0)
        records=app.base.read_json(self.root/'saida/previsao_execution.json')['rows']
        self.assertEqual(len(records),2)
        self.assertTrue(all(len(r['_read_attempts'])==2 for r in records))

    def test_apply_partial_results_not_counted_as_success(self):
        self.plan.update(orchestrator_version=1,inspection=[])
        app.base.save_json(app.resolver.PLAN,self.plan)
        def fail(*args,**kwargs):
            app.base.save_json(app.resolver.LEDGER,{'k':dict(before={'sys_id':'a'*32},status='uncertain')})
            raise app.base.Stop('Falha simulada')
        with patch.object(app.resolver,'apply',side_effect=fail), patch.object(app.inspector,'inspect') as inspect, patch('sys.stdout',new_callable=io.StringIO), patch('sys.stderr',new_callable=io.StringIO):
            self.assertEqual(app.run(None,{}, {}, [],'aplicar'),2)
            inspect.assert_not_called()
        result=app.base.read_json(self.root/'saida/resumo_chamados.json')
        self.assertEqual(result['resolucoes_confirmadas'],0)
        self.assertEqual(result['incertos'],1)
        self.assertEqual(result['rows'][1]['resultado'],'Não executado')

    def test_old_preview_rejected(self):
        app.base.save_json(app.resolver.PLAN,self.plan)
        with self.assertRaises(app.base.Stop): app.run(None,{}, {}, [],'aplicar')

    def test_inspection_error_still_generates_report(self):
        with patch.object(app.resolver,'preview',return_value=self.plan), patch.object(app.inspector,'inspect',side_effect=RuntimeError('Workspace indisponível')), patch('sys.stdout',new_callable=io.StringIO), patch('sys.stderr',new_callable=io.StringIO):
            self.assertEqual(app.run(None,{}, {}, [],'prever'),2)
        self.assertTrue((self.root/'saida/resumo_chamados.html').exists())

    def test_report_rows_per_registration_and_empty_ambiguous_cpf(self):
        report_data.render_report(self.root, [dict(chamado='RITM0000001',franquia='<Franquia>',
            matriculas=['SP123000001','SP123000002'],data_abertura='06-10-2026',cpfs={'SP123000001':'123.456.789-01'})])
        page=(self.root/'saida/previsao_chamados.html').read_text(encoding='utf-8')
        self.assertEqual(page.count('<td>RITM0000001</td>'),2)
        self.assertEqual(page.count('&lt;Franquia&gt;'),2)
        self.assertIn('2 registros · 1 chamados',page)
        self.assertIn('favicon.ico',page)
        self.assertNotIn('<style>',page)
        self.assertNotIn('Conferido',page)
        self.assertEqual(page.count('<th>'),5)
        self.assertIn('<td>SP123000002</td><td></td>',page)

    def test_franchise_repair_is_display_only_and_preserves_correct_names(self):
        repairs={'CartÃ£o de Juazeiro':'Cartão de Juazeiro','CartÃ£o de MossorÃ³':'Cartão de Mossoró',
                 'CARTÃƒO DE GOIANA':'CARTÃO DE GOIANA'}
        for raw,expected in repairs.items():
            self.assertEqual(report_data.franchise_for_html(raw),expected)
        for value in ('Cartão de São Paulo','CARTAO DE SAO LEOPOLDO','CCARTAO DE TIMBAUBA','JOÃO','Ângela','—'):
            self.assertEqual(report_data.franchise_for_html(value),value)
        self.assertEqual(report_data.franchise_for_html(''),'—')
        record=dict(chamado='INC0000001',franquia='CartÃ£o de Juazeiro',matriculas=['SP123000001'])
        original=copy.deepcopy(record)
        report_data.render_report(self.root,[record])
        self.assertEqual(record,original)
        self.assertIn('Cartão de Juazeiro',(self.root/'saida/previsao_chamados.html').read_text(encoding='utf-8'))

    def test_cpf_explicit_pairs_only_and_conflicts_blank(self):
        registrations=['SP123000001','SP123000002']
        pairs=report_data.cpf_associations('Matrícula: SP123000001 CPF: 12345678901\nMatrícula: SP123000002 CPF: 23456789012',registrations)
        self.assertEqual(pairs,dict(SP123000001='123.456.789-01',SP123000002='234.567.890-12'))
        self.assertEqual(report_data.cpf_associations('CPF: 12345678901',registrations,'12345678901'),dict.fromkeys(registrations,''))
        self.assertEqual(report_data.cpf_associations('Matrícula: SP123000001 CPF: 12345678901',['SP123000001'],'23456789012')['SP123000001'],'')

    def test_parallel_independent_clients_bounded_and_order_preserved(self):
        client=Mock(); client.page.page.url='https://example.test/now/sow/list'
        client.page.page.locator.return_value.count.return_value=0
        active=0; peak=0; lock=Lock(); calls=[]
        @contextmanager
        def connected(config, **kwargs):
            own=Mock(); own.thread=get_ident()
            self.assertEqual(kwargs,dict(prompt=False,source_url=client.page.page.url))
            yield own
        def read(own,config,numbers,fields,**kwargs):
            nonlocal active,peak
            if own is not client:
                self.assertEqual(own.thread,get_ident())
                self.assertFalse(kwargs['export_results'])
                with lock:
                    active+=1; peak=max(peak,active); calls.append(own)
                time.sleep(0.03)
                with lock: active-=1
            return [dict(chamado=n,franquia='Franquia',matriculas=['SP123000001'],resultado='Conferido') for n in numbers]
        numbers=[f'INC{i:07d}' for i in range(1,8)]; finished=[]
        with patch.object(parallel.base,'connected',side_effect=connected), patch.object(parallel.inspector,'inspect',side_effect=read), patch('sys.stdout',new_callable=io.StringIO):
            rows=parallel.inspect_parallel(client,{},numbers,{},finished.append)
        self.assertEqual([r['chamado'] for r in rows],numbers)
        self.assertEqual(len(finished),7)
        self.assertGreater(peak,1); self.assertLessEqual(peak,3)
        self.assertEqual(len({id(c) for c in calls}),7)

    def test_parallel_divergence_stops_before_rest(self):
        client=Mock(); client.page.page.url='https://example.test'
        client.page.page.locator.return_value.count.return_value=0
        @contextmanager
        def connected(*args,**kwargs): yield Mock()
        def read(own,config,numbers,fields,**kwargs):
            return [dict(chamado=n,franquia='A' if own is client else 'B',matriculas=[]) for n in numbers]
        with patch.object(parallel.base,'connected',side_effect=connected), patch.object(parallel.inspector,'inspect',side_effect=read) as inspected, patch('sys.stdout',new_callable=io.StringIO):
            with self.assertRaisesRegex(app.base.Stop,'divergiu'):
                parallel.inspect_parallel(client,{},['INC0000001','INC0000002','INC0000003','INC0000004'],{},Mock())
        self.assertEqual(inspected.call_count,5)  # A divergência é relatada após os demais leitores terminarem.

    def test_worker_retries_only_failed_number_and_keeps_others(self):
        client=Mock(); client.page.page.url='https://example.test'
        client.page.page.locator.return_value.count.return_value=0
        calls={}; lock=Lock()
        @contextmanager
        def connected(*args,**kwargs): yield Mock()
        def read(own,config,numbers,fields,**kwargs):
            number=numbers[0]
            with lock:
                calls[number]=calls.get(number,0)+1
                attempt=calls[number]
            if number=='INC0000001' and attempt==1:
                raise RuntimeError('Timeout de leitura')
            if number=='INC0000003':
                return [dict(chamado=number,resultado='Falha de navegação',_stop_batch=True)]
            return [dict(chamado=number,resultado='Conferido',matriculas=['SP123000001'])]
        with patch.object(parallel.base,'connected',side_effect=connected), patch.object(parallel.inspector,'inspect',side_effect=read), patch('sys.stdout',new_callable=io.StringIO):
            rows=parallel.inspect_parallel(client,{},['INC0000001','INC0000002','INC0000003'],{},Mock(),controlled=False)
        self.assertEqual(calls,dict(INC0000001=2,INC0000002=1,INC0000003=2))
        self.assertNotIn('_worker_error',rows[0])
        self.assertTrue(rows[2]['_worker_error'])
        self.assertEqual(len(rows[0]['_read_attempts']),2)

    def test_validation_detects_all_report_field_changes(self):
        import validar_previsao as validation
        expected=dict(chamado='RITM0000001',franquia='A',matriculas=['SP123000001'],
                      cpfs={'SP123000001':'123.456.789-01'},data_abertura='01-10-2026',resultado='Conferido')
        actual=dict(expected,franquia='B',matriculas=['SP123000002'],cpfs={},data_abertura='02-10-2026')
        diffs=validation.differences([expected],[actual])
        self.assertEqual({d['campo'] for d in diffs},{'franquia','matriculas','cpfs','data_abertura'})
        self.assertEqual(validation.differences([expected],[dict(expected)]),[])
        self.assertTrue(validation.differences([expected],[]))

    def test_prever_and_aplicar_use_existing_browser(self):
        for command,flags in [('prever',[]),('aplicar',[]),('prever',['--visivel']),('aplicar',['--visivel'])]:
            with self.subTest(command=command,flags=flags), patch('sys.argv',['processar_chamados.py',command]+flags), patch.object(app.resolver,'settings',return_value=({}, {}, [])), patch.object(app.base,'execution_lock'), patch.object(app.base,'connected') as connect, patch.object(app,'run',return_value=0) as run:
                self.assertEqual(app.main(),0)
                connect.assert_called_once_with({})
                self.assertEqual(run.call_args.args[4],command)

    def test_removed_headless_options_are_rejected_without_connection(self):
        for flag in ['--invisivel','--headless']:
            with self.subTest(flag=flag), patch('sys.argv',['processar_chamados.py','prever',flag]), patch.object(app.base,'connected') as connect, patch('sys.stderr',new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as error:
                    app.main()
                self.assertEqual(error.exception.code,2)
                connect.assert_not_called()

    def test_parallel_reserves_capacity_before_opening(self):
        client=Mock(); client.page.page.locator.return_value.count.return_value=6
        with patch.object(parallel.base,'connected') as connect:
            with self.assertRaisesRegex(app.base.Stop,'Reserve três guias'):
                parallel.inspect_parallel(client,{},['INC0000001'],{},Mock())
            connect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
