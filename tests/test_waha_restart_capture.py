import unittest
from unittest.mock import patch, MagicMock
from app import create_app, db
from app.models import User, WahaInstance
from app.utils.waha import WahaAPI
from config import TestConfig


class WahaRestartCaptureTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.app_ctx = self.app.app_context()
        self.app_ctx.push()
        db.create_all()

        admin = User(username='admin_waha_test', email='admin_waha@crm.dev', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)

        instance = WahaInstance(
            name='Instância Teste',
            api_url='http://127.0.0.1:3000',
            session_name='default',
            is_default=True
        )
        db.session.add(instance)
        db.session.commit()

        self.admin_id = admin.id
        self.instance_id = instance.id

    def tearDown(self):
        db.session.remove()
        self.app_ctx.pop()

    def login_admin(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin_id)
            sess['_fresh'] = True

    @patch('app.utils.waha.requests.get')
    @patch('app.utils.waha.requests.post')
    @patch('app.utils.waha.requests.put')
    def test_restart_whatsapp_capture_working_session(self, mock_put, mock_post, mock_get):
        # Mock GET /api/sessions/default -> WORKING
        resp_session = MagicMock()
        resp_session.status_code = 200
        resp_session.json.return_value = {
            "name": "default",
            "status": "WORKING"
        }

        # Mock GET /api/sessions?all=true (health check)
        resp_health = MagicMock()
        resp_health.status_code = 200
        resp_health.json.return_value = [{"name": "default"}]

        mock_get.side_effect = lambda url, **kwargs: (
            resp_session if 'sessions/default' in url else resp_health
        )

        # Mock POST /api/sessions/default/restart -> 200
        resp_restart = MagicMock()
        resp_restart.status_code = 200
        resp_restart.json.return_value = {"status": "WORKING"}
        mock_post.return_value = resp_restart

        # Mock PUT /api/sessions/default (ensure webhook) -> 200
        resp_webhook = MagicMock()
        resp_webhook.status_code = 200
        resp_webhook.json.return_value = {"status": "WORKING"}
        mock_put.return_value = resp_webhook

        result = WahaAPI.restart_whatsapp_capture(instance_id=self.instance_id)

        self.assertTrue(result['ok'])
        self.assertIn('captura de mensagens', result['message'].lower())
        self.assertEqual(len(result['steps']), 5)
        # Verifica se todos os passos foram concluídos com status ok
        for step in result['steps']:
            self.assertEqual(step['status'], 'ok')

    @patch('app.utils.waha.requests.get')
    @patch('app.utils.waha.requests.post')
    @patch('app.utils.waha.requests.put')
    def test_restart_whatsapp_capture_not_found_creates_session(self, mock_put, mock_post, mock_get):
        # Mock GET /api/sessions/default -> 404 primeiro, depois SCAN_QR_CODE
        resp_health = MagicMock()
        resp_health.status_code = 200
        resp_health.json.return_value = []

        resp_404 = MagicMock()
        resp_404.status_code = 404

        resp_created = MagicMock()
        resp_created.status_code = 200
        resp_created.json.return_value = {"name": "default", "status": "SCAN_QR_CODE"}

        # Primeira chamada GET health, segunda chamada GET sessão
        get_calls = [resp_health, resp_404, resp_created]
        mock_get.side_effect = lambda url, **kwargs: get_calls.pop(0) if get_calls else resp_created

        # Mock POST /api/sessions (create session)
        resp_post = MagicMock()
        resp_post.status_code = 201
        resp_post.json.return_value = {"name": "default", "status": "SCAN_QR_CODE"}
        mock_post.return_value = resp_post

        # Mock PUT webhook
        resp_webhook = MagicMock()
        resp_webhook.status_code = 200
        mock_put.return_value = resp_webhook

        result = WahaAPI.restart_whatsapp_capture(instance_id=self.instance_id)

        self.assertTrue(result['ok'])
        self.assertEqual(result['session_status'], 'SCAN_QR_CODE')
        self.assertIn('qr code', result['message'].lower())

    def test_api_waha_restart_capture_endpoint(self):
        self.login_admin()
        mock_res = {
            "ok": True,
            "message": "Sessão reiniciada com sucesso!",
            "session_status": "WORKING",
            "steps": [
                {"title": "Conectividade WAHA", "status": "ok", "detail": "Online"},
                {"title": "Reinicialização da Sessão", "status": "ok", "detail": "WORKING"}
            ]
        }
        with patch.object(WahaAPI, 'restart_whatsapp_capture', return_value=mock_res):
            resp = self.client.post('/admin/api/waha/restart_capture', json={"instance_id": self.instance_id})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data['ok'])
            self.assertEqual(data['message'], "Sessão reiniciada com sucesso!")
            self.assertEqual(len(data['steps']), 2)

    def test_form_waha_restart_capture_endpoint(self):
        self.login_admin()
        mock_res = {
            "ok": True,
            "message": "Sessão restabelecida!",
            "session_status": "WORKING",
            "steps": []
        }
        with patch.object(WahaAPI, 'restart_whatsapp_capture', return_value=mock_res):
            resp = self.client.post(f'/admin/waha/{self.instance_id}/restart_capture', follow_redirects=False)
            self.assertEqual(resp.status_code, 302)
            self.assertIn('/admin/settings?tab=waha', resp.location)


if __name__ == '__main__':
    unittest.main()
