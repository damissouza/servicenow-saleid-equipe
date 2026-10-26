"""Fixtures ficticias; testes sem ServiceNow e sem publicacao real."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

import publicar_site as site
import processar_chamados as app
import historico_venda_ativa as history


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'saida').mkdir()
        self.path = self.root / 'saida/historico_venda_ativa.json'
        self.data = dict(schema_version=1, marcador='Venda Ativa', rows=[dict(
            chamado='INC0000001', matricula='SP000000001', franquia='FICTICIA', cpf='00000000000', uc='0001',
            data_abertura='01-01-2026 08:00:00', data_resolucao='02-01-2026 09:00:00', sys_id='nao-enviar')])
        self.path.write_text(json.dumps(self.data), encoding='utf-8')
        self.config = {'assignee_email': 'operador@example.invalid'}
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def state(self):
        return json.loads((self.root / 'saida' / site.STATE).read_text(encoding='utf-8'))

    def test_success_preserves_local_history_and_never_saves_password(self):
        self.data['rows'].append(dict(self.data['rows'][0], chamado='INC0000002', matricula=''))
        self.path.write_text(json.dumps(self.data), encoding='utf-8')
        before = self.path.read_bytes()
        sender = Mock(return_value={'total': 3, 'added': 1})
        site.synchronize(self.root, self.config, password_fn=lambda prompt: 'senha-ficticia', publish_fn=sender)
        payload = sender.call_args.args[0]
        self.assertEqual(len(payload['rows']), 1)
        self.assertNotIn('sys_id', payload['rows'][0])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.state()['status'], 'confirmed')
        self.assertEqual(self.state()['skipped'], 1)
        self.assertNotIn('senha-ficticia', json.dumps(self.state()))
        self.assertNotIn('operador@example.invalid', json.dumps(self.state()))

    def test_pending_review_never_requests_password_or_sends(self):
        (self.root / 'saida/historico_venda_ativa_pendente.json').write_text('{}')
        password = Mock()
        sender = Mock()
        with self.assertRaises(site.PublicationPending):
            site.synchronize(self.root, self.config, password_fn=password, publish_fn=sender)
        password.assert_not_called()
        sender.assert_not_called()

    def test_network_failure_records_pending_and_retry_is_publication_only(self):
        sender = Mock(side_effect=urllib.error.URLError('offline'))
        with self.assertRaises(site.PublicationPending):
            site.synchronize(self.root, self.config, password_fn=lambda prompt: 'ficticia', publish_fn=sender)
        sender.assert_called_once()
        self.assertEqual(self.state()['reason'], 'network_uncertain')
        retry = Mock(return_value={'total': 1, 'added': 0, 'unchanged': True})
        site.synchronize(self.root, self.config, password_fn=lambda prompt: 'ficticia', publish_fn=retry)
        retry.assert_called_once()
        self.assertEqual(self.state()['status'], 'confirmed')

    def test_cancelled_password_preserves_pending(self):
        password = Mock(side_effect=EOFError())
        sender = Mock()
        with self.assertRaises(site.PublicationPending):
            site.synchronize(self.root, self.config, password_fn=password, publish_fn=sender)
        sender.assert_not_called()
        self.assertEqual(self.state()['status'], 'pending')

    def test_invalid_publication_record_is_not_overwritten(self):
        p = self.root / 'saida' / site.STATE
        p.write_text('{INVALIDO', encoding='utf-8')
        with self.assertRaises(site.PublicationPending):
            site.synchronize(self.root, self.config, password_fn=Mock(), publish_fn=Mock())
        self.assertEqual(p.read_text(), '{INVALIDO')

    def run_apply(self, publish_error=None):
        plan_path = self.root / 'saida/plan.json'
        plan_path.write_text(json.dumps({'orchestrator_version': 1, 'numbers': [], 'items': []}))
        with patch.object(app, 'ROOT', self.root), patch.object(app.resolver, 'PLAN', plan_path), \
             patch.object(app.resolver, 'LEDGER', self.root / 'saida/ledger.json'), \
             patch.object(app.resolver, 'apply') as apply, \
             patch.object(history, 'update', return_value=1), patch.object(app, 'report') as report, \
             patch.object(app.site, 'synchronize', side_effect=publish_error) as publish:
            result = app.run(None, {}, self.config, [], 'aplicar')
            apply.assert_called_once()
            publish.assert_called_once_with(self.root, self.config)
            return result, report.call_args.args[2]

    def test_apply_automatically_publishes_after_local_save(self):
        result, error = self.run_apply()
        self.assertEqual(result, 0)
        self.assertEqual(error, '')

    def test_publication_failure_never_repeats_resolution(self):
        result, error = self.run_apply(site.PublicationPending('publicacao pendente'))
        self.assertEqual(result, 2)
        self.assertIn('publicacao pendente', error)


if __name__ == '__main__':
    unittest.main()
