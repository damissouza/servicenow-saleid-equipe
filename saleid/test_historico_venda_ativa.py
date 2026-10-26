import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import processar_chamados as app
import historico_venda_ativa as history


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.out=self.root/'saida'
        self.root.mkdir(exist_ok=True)
        (self.root/'previsao_chamados.css').write_text('table{color:green}',encoding='utf-8')
        self.config={'selection_marker':'Venda ativa'}
        self.plan=dict(orchestrator_version=1,config_hash=app.base.digest(self.config),scope={'tag_id':'a'*32},
            inspection=[dict(chamado='INC0000001',franquia='CartÃ£o de Juazeiro',matriculas=['SP123000001','SP123000002'],
                cpfs={'SP123000001':'123.456.789-01'},data_abertura='06-10-2026 08:00:00')],
            items=[{'number':'INC0000001','sys_id':'b'*32}])
        self.after={'key':dict(number='INC0000001',before={'sys_id':'b'*32},status='fields_verified_comment_pending')}

    def update(self,before=None,after=None):
        return history.update(self.root,self.config,self.plan,before or {},self.after if after is None else after,review=False)

    def test_confirmed_only_with_multiple_registrations_and_same_css(self):
        self.assertEqual(self.update(),2)
        data=history.load(self.out)
        self.assertEqual(len(data['rows']),2)
        page=(self.out/'historico_venda_ativa.html').read_text(encoding='utf-8')
        self.assertIn('2 registros · 1 chamados',page)
        self.assertIn('Cartão de Juazeiro',page)
        self.assertEqual(page.count('<th>'),8)
        self.assertIn('<th>Incidente/Solicitação</th><th>Franquia</th><th>Matricula</th><th>CPF</th><th>UC</th><th>Data de abertura</th><th>Data de atribuição ao analista</th><th>Data de resolução</th>',page)
        self.assertIn('favicon.ico',page)
        self.assertTrue((self.out/'historico_venda_ativa.css').read_bytes().startswith((self.root/'previsao_chamados.css').read_bytes()))
        self.assertFalse((self.out/'previsao_chamados.html').exists())
        self.assertEqual(data['rows'][0]['franquia'],'CartÃ£o de Juazeiro')

    def test_assignment_survives_future_updates_without_a_confirmed_date(self):
        self.plan['inspection'][0]['data_atribuicao']='06-10-2026 09:00:00'
        self.update()
        self.plan['inspection'][0]['data_atribuicao']=''
        self.update()
        rows=history.load(self.out)['rows']
        self.assertTrue(all(row['data_atribuicao']=='06-10-2026 09:00:00' for row in rows))
        self.assertIn('06-10-2026 09:00:00', (self.out/'historico_venda_ativa.html').read_text(encoding='utf-8'))

    def test_assignment_must_remain_a_valid_text_date(self):
        self.update()
        data=history.load(self.out)
        for value in (123, '31-02-2026 09:00:00'):
            data['rows'][0]['data_atribuicao']=value
            with self.assertRaises(ValueError):
                history.validate(data)

    def test_uncertain_old_and_wrong_marker_excluded(self):
        self.assertEqual(self.update(before=self.after),0)
        self.assertEqual(self.update(after={'key':dict(self.after['key'],status='uncertain')}),0)
        self.config['selection_marker']='Validando'
        self.assertEqual(self.update(),0)
        self.assertFalse(self.out.exists())

    def test_invalid_preview_excluded(self):
        self.plan['inspection_error']='Falha persistente'
        self.assertEqual(self.update(),0)
        self.assertFalse(self.out.exists())

    def test_duplicates_preserve_nonempty_and_backup(self):
        self.update();previous=(self.out/'historico_venda_ativa.json').read_bytes()
        self.plan['inspection'][0].update(franquia='',cpfs={})
        self.update()
        rows=history.load(self.out)['rows']
        self.assertEqual(len(rows),2)
        self.assertTrue(all(r['franquia']=='CartÃ£o de Juazeiro' for r in rows))
        self.assertEqual(next(r['cpf'] for r in rows if r['matricula']=='SP123000001'),'123.456.789-01')
        backups=list((self.out.parent/'backups/historico_venda_ativa').glob('*.json'))
        self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),previous)

    def test_invalid_json_is_not_replaced(self):
        self.out.mkdir();path=self.out/'historico_venda_ativa.json';path.write_bytes(b'{invalid')
        with self.assertRaisesRegex(app.base.Stop,'sem criar uma base vazia'):self.update()
        self.assertEqual(path.read_bytes(),b'{invalid')
        self.assertFalse((self.out/'historico_venda_ativa.html').exists())

    def test_atomic_failure_preserves_previous_json(self):
        self.update();path=self.out/'historico_venda_ativa.json';before=path.read_bytes()
        with patch.object(history.os,'replace',side_effect=OSError('Disco indisponível')):
            with self.assertRaises(OSError):self.update()
        self.assertEqual(path.read_bytes(),before)

    def test_keeps_only_30_generated_backups(self):
        self.update();folder=self.out.parent/'backups/historico_venda_ativa';folder.mkdir(parents=True)
        for i in range(35):
            (folder/f'historico_venda_ativa_20200101T000000{i:06d}Z.json').write_bytes((self.out/'historico_venda_ativa.json').read_bytes())
        (folder/'anotacao_usuario.txt').write_text('preservar',encoding='utf-8')
        self.update()
        self.assertEqual(len(list(folder.glob('historico_venda_ativa_*.json'))),30)
        self.assertTrue((folder/'anotacao_usuario.txt').exists())
        self.assertFalse((folder/'historico_venda_ativa_20200101T000000000000Z.json').exists())

    def test_same_key_resumed_confirmation_is_included(self):
        before={'key':dict(self.after['key'],status='uncertain')}
        self.assertEqual(self.update(before=before),2)

    def test_dates_read_from_parent_in_utc_and_formatted_for_brasilia(self):
        client=Mock()
        client.rows.return_value=[dict(sys_id='b'*32,number='RITM0000001',state='3',opened_at='2026-10-06 14:00:00',closed_at={'value':'2026-10-06 16:42:20','display_value':'WRONG'})]
        result=history.read_resolution_date(client,'RITM0000001','b'*32)
        self.assertEqual(result['data_resolucao'],'06-10-2026 13:42:20')
        self.assertEqual(client.rows.call_args.args[0],'sc_req_item')
        self.assertEqual(client.rows.call_count,1)
        client.rows.return_value[0]['closed_at']=''
        self.assertEqual(history.read_resolution_date(client,'RITM0000001','b'*32,max_wait_seconds=0)['data_resolucao'],'')
        client.rows.side_effect=RuntimeError('HTTP 403')
        result=history.read_resolution_date(client,'RITM0000001','b'*32)
        self.assertEqual(result['data_resolucao'],'');self.assertIn('403',result['error'])

    def test_delayed_ritm_closure_retries_only_reads(self):
        client=Mock()
        open_row=dict(sys_id='b'*32,number='RITM0000001',state='2',opened_at='2026-10-06 14:00:00',closed_at='')
        closed_row=dict(open_row,state='3',closed_at='2026-10-06 16:42:20')
        client.rows.side_effect=[[open_row],[closed_row]]
        with patch.object(history.time,'sleep'):
            result=history.read_resolution_date(client,'RITM0000001','b'*32)
        self.assertEqual(result['data_resolucao'],'06-10-2026 13:42:20')
        self.assertEqual(result['read_attempts'],2)
        client.request.assert_not_called()

    def test_resolution_date_timeout_keeps_empty_without_substitution(self):
        client=Mock()
        client.rows.return_value=[dict(sys_id='b'*32,number='RITM0000001',state='2',opened_at='2026-10-06 14:00:00',closed_at='')]
        result=history.read_resolution_date(client,'RITM0000001','b'*32,max_wait_seconds=0)
        self.assertEqual(result['data_resolucao'],'')
        client.request.assert_not_called()

    def test_resolution_order_and_reference_keep_leading_zeros(self):
        self.update()
        reference=self.root/'saida/franquias_referencia.json'
        reference.write_text(json.dumps({'rows':[dict(matricula='SP123000001',franquia='Referência',cpf='00123456789',uc='000123')]}),encoding='utf-8')
        self.plan['inspection'][0]['data_abertura']='01-09-2026 10:00:00'
        self.after['key']['resolution_date']={'data_resolucao':'06-10-2026 13:41:41'}
        self.update()
        row=next(r for r in history.load(self.out)['rows'] if r['matricula']=='SP123000001')
        self.assertEqual((row['cpf'],row['uc']),('00123456789','000123'))
        self.assertEqual(row['data_resolucao'],'06-10-2026 13:41:41')
        newer=dict(row,chamado='INC0000002',data_abertura='01-08-2026 10:00:00',data_resolucao='07-10-2026 10:00:00',aplicado_em='2020-01-01T00:00:00+00:00')
        data=history.load(self.out);data['rows'].append(newer)
        undated=dict(row,chamado='INC0000003',data_abertura='08-10-2026 10:00:00',data_resolucao='')
        data['rows'].append(undated)
        history.write_data(self.root,data,self.out)
        self.assertEqual(history.load(self.out)['rows'][0]['chamado'],'INC0000001')
        self.assertEqual(history.load(self.out)['rows'][2]['chamado'],'INC0000002')
        self.assertEqual(history.load(self.out)['rows'][-1]['chamado'],'INC0000003')

    def test_invalid_duplicate_rows_are_rejected(self):
        self.update();path=self.out/'historico_venda_ativa.json';data=history.load(self.out)
        data['rows'].append(copy.deepcopy(data['rows'][0]));path.write_text(json.dumps(data),encoding='utf-8')
        saved=path.read_bytes()
        with self.assertRaises(app.base.Stop):self.update()
        self.assertEqual(path.read_bytes(),saved)

    def test_review_cancel_and_resume_without_writing_history(self):
        with patch('builtins.input',return_value='CANCELAR'):
            with self.assertRaisesRegex(app.base.Stop,'cancelada'):
                history.update(self.root,self.config,self.plan,{},self.after)
        self.assertTrue((self.out/history.PENDING).exists())
        self.assertFalse((self.out/(history.NAME+'.json')).exists())
        answers=iter(['NOME_FANTASIA\tMATRICULA\tCPF\tUC','Franquia A\tSP123000002\t00123456789\t00012','Franquia B\tSP123000001\t00234567890\t00034','FIM','GRAVAR'])
        self.assertEqual(history.review_pending(self.root,input_fn=lambda prompt:next(answers)),2)
        self.assertFalse((self.out/history.PENDING).exists())
        rows=history.load(self.out)['rows']
        self.assertEqual(next(r for r in rows if r['matricula']=='SP123000002')['uc'],'00012')
        self.assertEqual(next(r for r in rows if r['matricula']=='SP123000001')['cpf'],'00234567890')

    def test_review_requires_explicit_confirmation_and_keeps_original(self):
        self.update();original=(self.out/(history.NAME+'.json')).read_bytes()
        answers=iter(['Franquia A\tSP123000002\t00123456789\t00012','Franquia B\tSP123000001\t00234567890\t00034','FIM','NAO'])
        with patch('builtins.input',side_effect=lambda prompt:next(answers)):
            with self.assertRaisesRegex(app.base.Stop,'não confirmada'):
                history.update(self.root,self.config,self.plan,{},self.after)
        self.assertEqual((self.out/(history.NAME+'.json')).read_bytes(),original)
        self.assertFalse((self.out.parent/'backups').exists())

    def test_review_does_not_replace_history_changed_after_pending(self):
        with patch('builtins.input',return_value='CANCELAR'):
            with self.assertRaises(app.base.Stop):history.update(self.root,self.config,self.plan,{},self.after)
        self.update()
        with self.assertRaisesRegex(app.base.Stop,'mudou após'):
            history.review_pending(self.root,input_fn=lambda prompt:self.fail('Não deve pedir dados antes de validar a base'))

    def test_pasted_table_validates_duplicates_and_preserves_text(self):
        line='CARTAO DE TESTE\tBA300010961\t01135632561\t0030030989'
        parsed=history.parse_reference_table('NOME_FANTASIA\tMATRICULA\tCPF\tUC\n'+line+'\n'+line)
        self.assertEqual(len(parsed),1)
        self.assertEqual(parsed['BA300010961']['cpf'],'01135632561')
        self.assertEqual(parsed['BA300010961']['uc'],'0030030989')
        with self.assertRaisesRegex(ValueError,'conflitantes'):
            history.parse_reference_table(line+'\n'+line.replace('0030030989','00000'))
        with self.assertRaisesRegex(ValueError,'quatro colunas'):
            history.parse_reference_table('Franquia\tBA300010961\t01135632561')

    def test_missing_registration_does_not_block_others_and_is_preserved(self):
        self.plan['items'].append(dict(number='RITM0000002',sys_id='c'*32))
        self.plan['inspection'].append(dict(chamado='RITM0000002',matriculas=[],franquia='Pendente',data_abertura='06-10-2026 09:00:00'))
        self.after['other']=dict(number='RITM0000002',before={'sys_id':'c'*32},status='fields_verified_comment_pending')
        answers=iter(['Franquia A\tSP123000001\t00123456789\t00012','Franquia B\tSP123000002\t00234567890\t00034','FIM','GRAVAR'])
        with patch('builtins.input',side_effect=lambda prompt:next(answers)):
            history.update(self.root,self.config,self.plan,{},self.after)
        self.assertEqual(len(history.load(self.out)['rows']),2)
        pending=app.base.read_json(self.out/history.PENDING)
        self.assertEqual(pending['keys'],[['RITM0000002','']])
        self.assertEqual(pending['base_digest'],app.base.digest(history.load(self.out)))
        self.assertTrue(any(r['chamado']=='RITM0000002' for r in pending['data']['rows']))
        with self.assertRaisesRegex(app.base.Stop,'Todos os registros'):
            history.review_pending(self.root,input_fn=lambda prompt:self.fail('Não deve pedir tabela dos já publicados'))

    def test_missing_pasted_registration_requests_remaining_rows(self):
        answers=iter(['Franquia A\tSP123000001\t00123456789\t00012','FIM','Franquia B\tSP123000002\t00234567890\t00034','Franquia extra\tSP123000003\t00345678901\t00056','FIM','GRAVAR'])
        with patch('builtins.input',side_effect=lambda prompt:next(answers)):
            self.assertEqual(history.update(self.root,self.config,self.plan,{},self.after),2)
        self.assertEqual(len(history.load(self.out)['rows']),2)


if __name__=='__main__':unittest.main()
