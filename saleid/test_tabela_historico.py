import copy
import tempfile
import unittest
from pathlib import Path
import tabela_historico as t


def row(number='INC0000001',registration='SP000000001'):
    return dict(chamado=number,matricula=registration,franquia='FICTICIA',cpf='00000000000',uc='00001',data_abertura='01-01-2026 00:00:00',data_resolucao='02-01-2026 00:00:00',aplicado_em='2026-01-02T03:00:00+00:00',entry_key='fake',sys_id='a'*32)


def data(rows):return dict(schema_version=1,marcador='Venda Ativa',rows=rows)


class Tests(unittest.TestCase):
    def test_five_columns_and_zeros(self):
        r=t.parse_table('NOME_FANTASIA\tMATRICULA\tCPF\tUC\tchamado\nFICTICIA\tsp000000001\t00000000000\t00001\tinc0000001')[0]
        self.assertEqual((r['chamado'],r['cpf'],r['uc']),('INC0000001','00000000000','00001'))

    def test_space_before_number(self):
        r=t.parse_table('NOME_FANTASIA\tMATRICULA\tCPF\tUC chamado\nFICTICIA\tSP000000001\t00000000000\tNULL INC0000001')[0]
        self.assertEqual((r['uc'],r['chamado']),('NULL','INC0000001'))

    def test_old_four_columns(self):
        r=t.parse_table('FICTICIA\tSP000000001\t00000000000\tNULL')[0]
        self.assertEqual(r['chamado'],'')

    def test_conflicting_duplicate_rejected(self):
        with self.assertRaises(ValueError):t.parse_table('F\tSP000000001\t00000000000\t001\tINC0000001\nF\tSP000000001\t00000000000\t002\tINC0000001')

    def test_exact_pair_and_dates(self):
        original=data([row(),row('INC0000002')]); saved=copy.deepcopy(original)
        incoming=t.parse_table('NOVA\tSP000000001\t00000000000\t00002\tINC0000001')
        result,updates,_=t.associate(original,None,incoming)
        self.assertEqual(len(updates),1)
        self.assertEqual(result['rows'][0]['franquia'],'NOVA')
        self.assertEqual(result['rows'][1]['franquia'],'FICTICIA')
        self.assertEqual(result['rows'][0]['data_resolucao'],original['rows'][0]['data_resolucao'])
        self.assertEqual(original,saved)

    def test_ambiguous_four_columns_rejected(self):
        with self.assertRaises(ValueError):t.associate(data([row(),row('INC0000002')]),None,t.parse_table('F\tSP000000001\t00000000000\t001'))

    def test_unknown_call_rejected(self):
        with self.assertRaises(ValueError):t.associate(data([row()]),None,t.parse_table('F\tSP000000001\t00000000000\t001\tINC0000002'))

    def test_fill_missing_registration_on_known_call(self):
        original=data([]);pending=dict(base_digest=t.base.digest(original),data=data([row(registration='')]),keys=[['INC0000001','']])
        result,updates,consumed=t.associate(original,pending,t.parse_table('F\tSP000000001\t00000000000\t001\tINC0000001'))
        self.assertEqual(result['rows'][0]['matricula'],'SP000000001')
        self.assertEqual(consumed,{('INC0000001','')})

    def test_review_partial_pending_then_published(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out=root/'saida';out.mkdir();(root/'previsao_chamados.css').write_text('table{}',encoding='utf-8')
            original=data([])
            pending=dict(base_digest=t.base.digest(original),data=data([row(),row('INC0000002','SP000000002')]),keys=[['INC0000001','SP000000001'],['INC0000002','SP000000002']])
            t.base.save_json(out/t.history.PENDING,pending)
            answers=iter(['F\tSP000000001\t00000000000\t00002\tINC0000001','FIM','GRAVAR'])
            self.assertEqual(t.review_table(root,input_fn=lambda _:next(answers)),1)
            self.assertEqual(len(t.history.load(out)['rows']),1)
            remaining=t.base.read_json(out/t.history.PENDING)
            self.assertEqual(remaining['keys'],[['INC0000002','SP000000002']])
            self.assertEqual(remaining['base_digest'],t.base.digest(t.history.load(out)))
            answers=iter(['OUTRA\tSP000000001\t00000000000\tNULL\tINC0000001','FIM','GRAVAR'])
            t.review_table(root,input_fn=lambda _:next(answers))
            self.assertEqual(t.history.load(out)['rows'][0]['franquia'],'OUTRA')
            self.assertEqual(len(list((root/'backups').rglob('*.json')))>0,True)

    def test_no_confirmation_leaves_all_intact(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out=root/'saida';out.mkdir();(root/'previsao_chamados.css').write_text('table{}',encoding='utf-8')
            t.history.write_data(root,data([row()]),out)
            saved=(out/'historico_venda_ativa.json').read_bytes()
            answers=iter(['F\tSP000000001\t00000000000\t001\tINC0000001','FIM','NAO'])
            with self.assertRaises(t.base.Stop):t.review_table(root,input_fn=lambda _:next(answers))
            self.assertEqual(saved,(out/'historico_venda_ativa.json').read_bytes())


if __name__=='__main__':unittest.main()
