"""Fixtures ficticias; nao acessa ServiceNow nem painel real."""
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import configurar
import publicar_resultados as publisher


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_setup_configura_email_e_assinatura_sem_sobrescrever(self):
        for p in (configurar.ROOT / 'saleid').glob('*.example.*'):
            shutil.copy2(p, self.root / p.name)
        args = (self.root, 'operador@example.invalid', 'Operador Ficticio', 'https://example.service-now.com', 'INC0000001', 'RITM0000001', 'INC0000001')
        configurar.prepare(*args)
        config = json.loads((self.root / 'config_resolucao.json').read_text(encoding='utf-8'))
        self.assertEqual(config['assignee_email'], args[1])
        matches = {key for key in config['resolution_confirmed_markers'] + list(config['selection_tag_references']) if key.casefold() == 'venda ativa'}
        self.assertEqual(len(matches), 1)
        self.assertIn('Operador Ficticio', (self.root / 'resposta_resolucao.txt').read_text(encoding='utf-8'))
        with self.assertRaises(ValueError):
            configurar.prepare(*args)

    def sample(self):
        return {'schema_version': 1, 'marcador': 'Venda Ativa', 'rows': [dict(chamado='INC0000001', matricula='SP000000001', franquia='FRANQUIA FICTICIA', cpf='00000000000', uc='0001', data_abertura='01-01-2026 08:00:00', data_resolucao='02-01-2026 09:00:00', sys_id='nao-enviar', entry_key='nao-enviar')]}

    def test_publicador_projeta_somente_campos_do_painel(self):
        path = self.root / 'dados.json'
        path.write_text(json.dumps(self.sample()), encoding='utf-8')
        row = publisher.read_payload(path)['rows'][0]
        self.assertEqual(set(row), set(publisher.FIELDS))
        self.assertEqual(row['uc'], '0001')
        self.assertNotIn('sys_id', row)

    def test_sem_resolucao_ou_matricula_nao_publica(self):
        for field in ['matricula', 'data_resolucao']:
            sample = self.sample()
            sample['rows'][0][field] = ''
            path = self.root / 'dados.json'
            path.write_text(json.dumps(sample), encoding='utf-8')
            with self.assertRaises(ValueError):
                publisher.read_payload(path)

    def test_login_versao_e_importacao_sem_substituir_rota_original(self):
        class Client:
            def __init__(self):
                self.requests = []

            def open(self, req, timeout):
                self.requests.append(req)
                value = {} if len(self.requests) == 1 else {'version': 'versao-ficticia'} if len(self.requests) == 2 else {'total': 2, 'added': 1}
                return io.BytesIO(json.dumps(value).encode())
        client = Client()
        result = publisher.publish(self.sample(), 'operador@example.invalid', 'senha-ficticia', client)
        self.assertEqual(result['added'], 1)
        self.assertEqual([req.full_url for req in client.requests], [publisher.SITE + '/auth/start', publisher.SITE + '/api/historico', publisher.SITE + '/api/historico/importar'])
        self.assertEqual(json.loads(client.requests[-1].data)['version'], 'versao-ficticia')
        self.assertNotIn(b'senha-ficticia', client.requests[-1].data)

    def test_redirecionamento_externo_recusado(self):
        with self.assertRaises(ValueError):
            publisher.SameSiteRedirect().redirect_request(None, None, 303, '', {}, 'https://example.invalid/roubar')


if __name__ == '__main__':
    unittest.main()
