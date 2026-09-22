import unittest
from unittest.mock import patch, MagicMock
from app import create_app, db
from app.models import Client, MessageLog
from app.tasks.whatsapp import process_whatsapp_message
from app.tasks.queue import is_duplicate_message

class TestAsyncWhatsAppWebhook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        cls.client = cls.app.test_client()
        with cls.app.app_context():
            db.create_all()

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.drop_all()

    def setUp(self):
        with self.app.app_context():
            db.session.query(MessageLog).delete()
            db.session.query(Client).delete()
            db.session.commit()

    @patch('app.api.routes.get_queue')
    @patch('app.api.routes.is_duplicate_message')
    def test_webhook_enqueues_valid_message(self, mock_is_dup, mock_get_queue):
        mock_is_dup.return_value = False
        mock_job = MagicMock()
        mock_job.id = 'test-job-1234'
        mock_queue = MagicMock()
        mock_queue.enqueue.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        payload = {
            "event": "message",
            "payload": {
                "id": "true_5511999998888@c.us_3EB012345678",
                "from": "5511999998888@c.us",
                "body": "Olá, gostaria de informações sobre os serviços.",
                "fromMe": False
            }
        }

        response = self.client.post('/api/webhook/whatsapp', json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data.get('status'), 'queued')
        self.assertEqual(data.get('job_id'), 'test-job-1234')
        mock_queue.enqueue.assert_called_once()

    @patch('app.api.routes.get_queue')
    @patch('app.api.routes.is_duplicate_message')
    def test_webhook_ignores_duplicate_message(self, mock_is_dup, mock_get_queue):
        mock_is_dup.return_value = True

        payload = {
            "event": "message",
            "payload": {
                "id": "duplicate-msg-id-999",
                "from": "5511999998888@c.us",
                "body": "Mensagem repetida",
                "fromMe": False
            }
        }

        response = self.client.post('/api/webhook/whatsapp', json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data.get('status'), 'ignored')
        self.assertEqual(data.get('reason'), 'duplicate_message')
        mock_get_queue.assert_not_called()

    def test_webhook_ignores_from_me(self):
        payload = {
            "event": "message",
            "payload": {
                "id": "my-msg-123",
                "from": "5511999998888@c.us",
                "body": "Mensagem minha",
                "fromMe": True
            }
        }
        response = self.client.post('/api/webhook/whatsapp', json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json().get('reason'), 'sent_by_me')

    def test_webhook_ignores_group_message(self):
        payload = {
            "event": "message",
            "payload": {
                "id": "grp-msg-123",
                "from": "123456789-987654@g.us",
                "body": "Mensagem de grupo",
                "fromMe": False
            }
        }
        response = self.client.post('/api/webhook/whatsapp', json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json().get('reason'), 'group_message')

    def test_webhook_ignores_empty_body(self):
        payload = {
            "event": "message",
            "payload": {
                "id": "empty-msg-123",
                "from": "5511999998888@c.us",
                "body": "   ",
                "fromMe": False
            }
        }
        response = self.client.post('/api/webhook/whatsapp', json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json().get('reason'), 'empty_body')

    def test_webhook_handles_messages_update(self):
        payload = {
            "event": "messages.update",
            "data": [{"id": "msg-1", "status": "READ"}]
        }
        response = self.client.post('/api/webhook/whatsapp', json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json().get('count'), 1)

    @patch('app.utils.waha.WahaAPI.send_text')
    @patch('app.utils.ai_handler.AIHandler.generate_reply')
    def test_process_whatsapp_message_task(self, mock_gen_reply, mock_send_text):
        mock_gen_reply.return_value = ("Olá João! Como posso ajudar?", None)
        mock_send_text.return_value = (True, {"id": "waha_out_1"})

        with self.app.app_context():
            # Cria cliente no banco
            client = Client(name="João Silva", phone="5511988887777", email="joao@example.com")
            db.session.add(client)
            db.session.commit()
            client_id = client.id

            payload = {
                "id": "msg-unique-test-1",
                "from": "5511988887777@c.us",
                "body": "Gostaria de agendar uma reunião.",
                "fromMe": False
            }

            result = process_whatsapp_message(payload, event="message")

            self.assertEqual(result.get('status'), 'completed')
            self.assertEqual(result.get('sent'), True)
            self.assertEqual(result.get('client_id'), client_id)
            self.assertEqual(result.get('reply'), "Olá João! Como posso ajudar?")

            # Verifica se MessageLog foi inserido
            log = MessageLog.query.filter_by(client_id=client_id).first()
            self.assertIsNotNone(log)
            self.assertEqual(log.channel, 'waha_api')
            self.assertEqual(log.status, 'sent')
            self.assertEqual(log.content, "Olá João! Como posso ajudar?")

if __name__ == '__main__':
    unittest.main()
