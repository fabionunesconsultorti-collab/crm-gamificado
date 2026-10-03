import unittest
from unittest.mock import patch, MagicMock
from app import create_app, db
from app.models import User, Client, MessageLog
from config import TestConfig

class TestBotToggleHumanoRobo(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.user = User(username='atendente_joao', role='admin')
        self.user.set_password('123456')
        db.session.add(self.user)
        db.session.commit()

        self.client_robo = Client(
            name='Lead com Bot Ativo',
            phone='(11) 91111-1111',
            status='lead',
            bot_enabled=True
        )
        self.client_humano = Client(
            name='Lead Atendimento Humano',
            phone='(11) 92222-2222',
            status='lead',
            bot_enabled=False
        )
        db.session.add_all([self.client_robo, self.client_humano])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.user.id)
            sess['_fresh'] = True

    def test_model_defaults_and_properties(self):
        new_c = Client(name='Novo Lead Teste')
        db.session.add(new_c)
        db.session.commit()
        self.assertTrue(new_c.bot_enabled)
        self.assertFalse(new_c.is_human_service)
        self.assertEqual(new_c.service_mode_label, 'Robô')

        new_c.bot_enabled = False
        db.session.commit()
        self.assertTrue(new_c.is_human_service)
        self.assertEqual(new_c.service_mode_label, 'Humano')

    def test_toggle_bot_endpoint(self):
        self._login()
        client_id = self.client_robo.id

        # Alterna para humano via POST sem body
        res = self.client.post(f'/crm/client/{client_id}/toggle-bot')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertFalse(data['bot_enabled'])
        self.assertEqual(data['mode'], 'humano')

        # Verifica persistência no banco
        c = Client.query.get(client_id)
        self.assertFalse(c.bot_enabled)

        # Define explicitamente como robo via JSON
        res2 = self.client.post(
            f'/crm/client/{client_id}/toggle-bot',
            json={'bot_enabled': True}
        )
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertTrue(data2['bot_enabled'])
        self.assertEqual(data2['mode'], 'robo')

        c = Client.query.get(client_id)
        self.assertTrue(c.bot_enabled)

    def test_client_form_create_and_edit_bot_mode(self):
        self._login()

        # Criação de novo lead como humano
        res_create = self.client.post('/crm/client/new', data={
            'name': 'Novo Cliente Humano',
            'phone': '(11) 93333-3333',
            'status': 'lead',
            'bot_enabled': 'humano'
        }, follow_redirects=True)
        self.assertEqual(res_create.status_code, 200)

        created = Client.query.filter_by(name='Novo Cliente Humano').first()
        self.assertIsNotNone(created)
        self.assertFalse(created.bot_enabled)

        # Edição para voltar para robô
        res_edit = self.client.post(f'/crm/client/{created.id}/edit', data={
            'name': 'Novo Cliente Humano',
            'phone': '(11) 93333-3333',
            'status': 'lead',
            'bot_enabled': 'robo'
        }, follow_redirects=True)
        self.assertEqual(res_edit.status_code, 200)

        db.session.refresh(created)
        self.assertTrue(created.bot_enabled)

    def test_kanban_bot_mode_filter(self):
        self._login()

        # Filtro bot_mode=humano deve trazer apenas self.client_humano
        res_humano = self.client.get('/crm/kanban?bot_mode=humano')
        self.assertEqual(res_humano.status_code, 200)
        html_humano = res_humano.get_data(as_text=True)
        self.assertIn('Lead Atendimento Humano', html_humano)
        self.assertNotIn('Lead com Bot Ativo', html_humano)

        # Filtro bot_mode=robo deve trazer apenas self.client_robo
        res_robo = self.client.get('/crm/kanban?bot_mode=robo')
        self.assertEqual(res_robo.status_code, 200)
        html_robo = res_robo.get_data(as_text=True)
        self.assertIn('Lead com Bot Ativo', html_robo)
        self.assertNotIn('Lead Atendimento Humano', html_robo)

    def test_whatsapp_task_respects_bot_disabled(self):
        from app.tasks.whatsapp import _do_process_whatsapp_message, _do_process_buffered_whatsapp_messages
        from app.utils.lead_enricher import LeadEnricher

        # 1. Processamento direto com cliente marcado como humano (bot desativado)
        payload = {
            'id': 'msg_test_123',
            'from': self.client_humano.phone,
            'body': 'Olá, preciso falar com um atendente',
            'fromMe': False
        }
        res = _do_process_whatsapp_message(payload)
        self.assertEqual(res.get('status'), 'human_mode_active')
        self.assertEqual(res.get('reason'), 'client_bot_disabled')
        self.assertEqual(res.get('client_id'), self.client_humano.id)

        # 2. Processamento em lote bufferizado também deve respeitar
        clean_phone = LeadEnricher.clean_digits(self.client_humano.phone)
        chat_id = f"{clean_phone}@c.us"
        with patch('app.tasks.buffer.is_valid_batch', return_value=True), \
             patch('app.tasks.buffer.acquire_chat_lock', return_value=True), \
             patch('app.tasks.buffer.pop_all_buffered_messages', return_value=[{'body': 'Oi, tudo bem?'}]), \
             patch('app.tasks.buffer.release_chat_lock') as mock_release:
            res_buffered = _do_process_buffered_whatsapp_messages(
                chat_id=chat_id,
                instance_id=1,
                batch_token='token_teste'
            )
            self.assertEqual(res_buffered.get('status'), 'human_mode_active')
            self.assertEqual(res_buffered.get('client_id'), self.client_humano.id)
            mock_release.assert_called_once()

if __name__ == '__main__':
    unittest.main()
