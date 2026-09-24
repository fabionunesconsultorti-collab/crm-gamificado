import json
import unittest
from unittest.mock import patch, MagicMock
from app import create_app, db
from app.models import User


from config import TestConfig


class BotLiveTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.app_ctx = self.app.app_context()
        self.app_ctx.push()
        db.create_all()

        # Cria usuário admin de teste
        admin = User(username='admin_test', email='admin_test@crm.dev', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        self.admin_id = admin.id

    def tearDown(self):
        db.session.remove()
        self.app_ctx.pop()

    def login_admin(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin_id)
            sess['_fresh'] = True

    def test_bot_live_page_renders(self):
        self.login_admin()
        response = self.client.get('/admin/bot/live')
        self.assertEqual(response.status_code, 200)
        content = response.data.decode('utf-8')
        self.assertIn('Central de Operações Autônomas', content)
        self.assertIn('Simulador WhatsApp', content)
        self.assertIn('Webhook WAHA', content)
        self.assertIn('Buffer & Debounce', content)
        self.assertIn('Inferência Ollama', content)

    def test_bot_live_events_api(self):
        self.login_admin()
        mock_events = [{
            "batch_id": "b123",
            "chat_id": "5511999990001@c.us",
            "step": "webhook_received",
            "step_index": 1,
            "step_title": "Webhook WAHA",
            "status": "completed"
        }]

        with patch('app.utils.live_tracker.LiveTracker.get_recent_events', return_value=mock_events), \
             patch('app.utils.live_tracker.LiveTracker.get_active_batches', return_value=[]), \
             patch('app.utils.live_tracker.LiveTracker.get_system_stats', return_value={"waha": {"online": True}}):

            response = self.client.get('/admin/bot/live-events')
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertTrue(data['ok'])
            self.assertEqual(len(data['events']), 1)
            self.assertEqual(data['events'][0]['step_title'], "Webhook WAHA")

    def test_bot_simulate_message(self):
        self.login_admin()
        with patch('app.tasks.buffer.add_to_buffer', return_value=('token_sim_123', 12)):
            response = self.client.post('/admin/bot/simulate-message', json={
                "message": "Olá, queria um orçamento de CRM",
                "chat_id": "5511999998888"
            })
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertTrue(data['ok'])
            self.assertEqual(data['batch_token'], 'token_sim_123')
            self.assertEqual(data['delay_seconds'], 12)


if __name__ == '__main__':
    unittest.main()
