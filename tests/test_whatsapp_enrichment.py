import unittest
from unittest.mock import patch, MagicMock
from app import create_app, db
from app.models import Client, Setting, MessageLog
from config import TestConfig
from app.tasks.whatsapp import _do_process_buffered_whatsapp_messages
from app.utils.lead_enricher import LeadEnricher

class TestWhatsAppEnrichmentIntegration(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    @patch('app.utils.conversation_memory.ConversationMemory')
    @patch('app.utils.waha.WahaAPI')
    @patch('app.utils.ai_handler.AIHandler')
    @patch('app.tasks.buffer.pop_all_buffered_messages')
    @patch('app.tasks.buffer.acquire_chat_lock', return_value=True)
    @patch('app.tasks.buffer.release_chat_lock', return_value=True)
    @patch('app.tasks.buffer.is_valid_batch', return_value=True)
    def test_auto_registration_with_pushname_and_formatted_phone(
        self, mock_is_valid, mock_release_lock, mock_acquire_lock,
        mock_pop_messages, mock_ai_handler, mock_waha, mock_memory
    ):
        """Valida se o auto-cadastro grava telefone formatado e pushName limpo"""
        mock_pop_messages.return_value = [
            {
                'id': 'msg_001',
                'body': 'Olá, gostaria de conhecer o sistema',
                'timestamp': 1000,
                'push_name': 'Juliana Silveira 🚀'
            }
        ]
        mock_memory.get_context_messages.return_value = []
        mock_ai_handler.generate_chat_reply.return_value = ("Olá Juliana! É um prazer. Qual a sua empresa?", None)
        mock_waha.send_text.return_value = (True, {"id": "waha_out_1"})

        chat_id = "5511988887777@c.us"
        res = _do_process_buffered_whatsapp_messages(chat_id=chat_id, batch_token="batch_tok_1")

        self.assertEqual(res.get('status'), 'completed')

        # Verifica se o cliente foi criado no banco
        client = Client.query.filter_by(name="Juliana Silveira").first()
        self.assertIsNotNone(client)
        self.assertEqual(client.phone, "(11) 98888-7777")
        self.assertEqual(client.status, "lead")

    @patch('app.utils.conversation_memory.ConversationMemory')
    @patch('app.utils.waha.WahaAPI')
    @patch('app.utils.ai_handler.AIHandler')
    @patch('app.tasks.buffer.pop_all_buffered_messages')
    @patch('app.tasks.buffer.acquire_chat_lock', return_value=True)
    @patch('app.tasks.buffer.release_chat_lock', return_value=True)
    @patch('app.tasks.buffer.is_valid_batch', return_value=True)
    def test_progressive_enrichment_accumulates_data_without_loss(
        self, mock_is_valid, mock_release_lock, mock_acquire_lock,
        mock_pop_messages, mock_ai_handler, mock_waha, mock_memory
    ):
        """Valida preenchimento progressivo de dados (email, segmento) sem perder dados anteriores"""
        # Cria cliente inicial
        client = Client(
            name="Marcos Vinicius",
            phone="(19) 97777-6666",
            status="lead",
            notes="Lead cadastrado previamente."
        )
        db.session.add(client)
        db.session.commit()
        client_id = client.id

        # Mensagem do lead informando email e ramo
        mock_pop_messages.return_value = [
            {
                'id': 'msg_002',
                'body': 'meu e-mail é marcos.v@agro.com.br e atuo no ramo de agronegócio',
                'timestamp': 2000,
                'push_name': 'Marcos'
            }
        ]
        mock_memory.get_context_messages.return_value = [
            {'role': 'assistant', 'content': 'Qual seu email e segmento?'}
        ]
        mock_ai_handler.generate_chat_reply.return_value = ("Perfeito Marcos, anotado!", None)
        mock_waha.send_text.return_value = (True, {"id": "waha_out_2"})

        chat_id = "5519977776666@c.us"
        res = _do_process_buffered_whatsapp_messages(chat_id=chat_id, batch_token="batch_tok_2")
        self.assertEqual(res.get('status'), 'completed')

        # Recarrega o cliente do banco de dados
        updated_client = db.session.get(Client, client_id)
        self.assertIsNotNone(updated_client)
        # NUNCA deve ter apagado nome ou telefone
        self.assertEqual(updated_client.name, "Marcos Vinicius")
        self.assertEqual(updated_client.phone, "(19) 97777-6666")
        # Enriquecimento com email e segmento
        self.assertEqual(updated_client.email, "marcos.v@agro.com.br")
        self.assertIn("Agronegócio", updated_client.segment)
        # Notas preservam histórico anterior e adicionam o novo
        self.assertIn("Lead cadastrado previamente.", updated_client.notes)
        self.assertIn("Bot Coletou", updated_client.notes)
        # Status promovido para contato com dados qualificados
        self.assertEqual(updated_client.status, "contato")

    @patch('app.utils.conversation_memory.ConversationMemory')
    @patch('app.utils.waha.WahaAPI')
    @patch('app.utils.ai_handler.AIHandler')
    @patch('app.tasks.buffer.pop_all_buffered_messages')
    @patch('app.tasks.buffer.acquire_chat_lock', return_value=True)
    @patch('app.tasks.buffer.release_chat_lock', return_value=True)
    @patch('app.tasks.buffer.is_valid_batch', return_value=True)
    def test_qualification_prompt_passed_to_ai_handler(
        self, mock_is_valid, mock_release_lock, mock_acquire_lock,
        mock_pop_messages, mock_ai_handler, mock_waha, mock_memory
    ):
        """Valida que o client_info passado para o AIHandler contém as diretrizes de qualificação"""
        mock_pop_messages.return_value = [
            {
                'id': 'msg_003',
                'body': 'Quero saber os valores do plano',
                'timestamp': 3000,
                'push_name': ''
            }
        ]
        mock_memory.get_context_messages.return_value = []
        mock_ai_handler.generate_chat_reply.return_value = ("Temos planos a partir de R$ 99. Qual o seu nome?", None)
        mock_waha.send_text.return_value = (True, {"id": "waha_out_3"})

        chat_id = "5521999991234@c.us"
        _do_process_buffered_whatsapp_messages(chat_id=chat_id, batch_token="batch_tok_3")

        # Verifica o que foi passado para generate_chat_reply
        self.assertTrue(mock_ai_handler.generate_chat_reply.called)
        _, kwargs = mock_ai_handler.generate_chat_reply.call_args
        client_info = kwargs.get('client_info')
        self.assertIsNotNone(client_info)
        self.assertIn('qualification_prompt', client_info)
        self.assertIn('DIRETRIZ DE COLETA ATIVA DE DADOS', client_info['qualification_prompt'])
        self.assertIn('Nome do cliente', client_info['qualification_prompt'])

if __name__ == '__main__':
    unittest.main()
