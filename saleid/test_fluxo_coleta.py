import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import processar_chamados as app
import historico_venda_ativa as history


class CollectionFlowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root/'saida').mkdir()
        (self.root/'previsao_chamados.css').write_text('table{}')
        app.base.save_json(self.root/'config_inspecao.json', {})
        for target, name, value in (
            (app, 'ROOT', self.root),
            (app.resolver, 'PLAN', self.root/'saida/plan.json'),
            (app.resolver, 'LEDGER', self.root/'saida/ledger.json'),
        ):
            item = patch.object(target, name, value)
            item.start()
            self.addCleanup(item.stop)
        self.plan = dict(numbers=['INC0000001'], items=[], skipped=[],
                         orchestrator_version=1, inspection=[], inspection_error='')

    def test_preview_collects_without_resolving(self):
        row=dict(chamado='INC0000001', matriculas=['SP0001'], resultado='Conferido')
        with patch.object(app.resolver, 'preview', return_value=copy.deepcopy(self.plan)), \
             patch.object(app.inspector, 'inspect', return_value=[row]) as inspect, \
             patch.object(app.resolver, 'apply') as apply:
            self.assertEqual(app.run(None, {}, {}, [], 'prever'), 0)
        inspect.assert_called_once()
        apply.assert_not_called()
        self.assertEqual(app.base.read_json(app.resolver.PLAN)['inspection'][0]['matriculas'], ['SP0001'])

    def test_failed_preview_inspection_prevents_application(self):
        with patch.object(app.resolver, 'preview', return_value=copy.deepcopy(self.plan)), \
             patch.object(app.inspector, 'inspect', side_effect=RuntimeError('offline')):
            self.assertEqual(app.run(None, {}, {}, [], 'prever'), 2)
        with patch.object(app.resolver, 'apply') as apply:
            with self.assertRaises(app.base.Stop):
                app.run(None, {}, {}, [], 'aplicar')
        apply.assert_not_called()

    def test_assignment_read_once_for_multiple_registrations(self):
        rows = [dict(chamado='INC0000001', sys_id='a'*32, data_abertura='23-10-2026 09:00:00',
                     data_resolucao='23-10-2026 11:00:00') for _ in range(2)]
        with patch('atividade_atribuicoes.ActivityReader') as factory:
            reader = factory.return_value.__enter__.return_value
            reader.read.return_value = '23-10-2026 10:00:00'
            history.collect_assignments(Mock(), rows, self.root)
            reader.read.assert_called_once()
        self.assertTrue(all(row['data_atribuicao']=='23-10-2026 10:00:00' for row in rows))

    def test_assignment_failure_preserves_existing_value(self):
        rows = [dict(chamado='INC0000001', sys_id='a'*32, data_abertura='23-10-2026 09:00:00',
                     data_atribuicao='23-10-2026 10:00:00', data_resolucao='23-10-2026 11:00:00')]
        with patch('atividade_atribuicoes.ActivityReader', side_effect=RuntimeError('offline')):
            history.collect_assignments(Mock(), rows, self.root)
        self.assertEqual(rows[0]['data_atribuicao'], '23-10-2026 10:00:00')


if __name__ == '__main__':
    unittest.main()
