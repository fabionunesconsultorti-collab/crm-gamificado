import unittest
from unittest.mock import patch, MagicMock
from app import create_app, db
from app.models import User, KnowledgeDoc, MessageLog, Setting
from app.utils.web_crawler import WebPageExtractor
from app.utils.faq_miner import FAQMiner
from config import TestConfig

class TestWebsiteAndFAQLearningRAG(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()

        db.create_all()

        # Cria admin para testes autenticados
        self.admin = User(username='admin_rag_web', email='admin_web@crm.com', role='admin')
        self.admin.set_password('senha123')
        db.session.add(self.admin)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_sanitize_url(self):
        """Testa a normalização e prefixação de protocolo em URLs."""
        self.assertEqual(WebPageExtractor.sanitize_url('minhaempresa.com.br'), 'https://minhaempresa.com.br')
        self.assertEqual(WebPageExtractor.sanitize_url('http://site.com'), 'http://site.com')
        self.assertEqual(WebPageExtractor.sanitize_url('https://site.com/planos'), 'https://site.com/planos')
        self.assertEqual(WebPageExtractor.sanitize_url(''), '')

    @patch('requests.get')
    def test_html_clean_and_extraction(self, mock_get):
        """Testa o parser do WebPageExtractor removendo scripts, menus e extraindo conteúdo substantivo."""
        fake_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Plano Pro CRM - Soluções Corporativas</title>
            <meta name="description" content="Tabela de preços oficial e recursos do Plano Pro.">
            <style>body { font-size: 16px; }</style>
            <script>console.log('tracker');</script>
        </head>
        <body>
            <header>
                <nav><a href="/">Home</a><a href="/login">Login</a></nav>
            </header>
            <main>
                <h1>Plano Pro CRM</h1>
                <p>O Plano Pro custa R$ 249 mensais e inclui automação total de WhatsApp e IA.</p>
                <h2>Recursos Inclusos</h2>
                <ul>
                    <li>Disparo em lote com proteção anti-ban</li>
                    <li>RAG com base de conhecimento própria</li>
                </ul>
            </main>
            <footer>
                <p>Copyright 2026 Todos os direitos reservados.</p>
            </footer>
        </body>
        </html>
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = fake_html
        mock_resp.encoding = 'utf-8'
        mock_get.return_value = mock_resp

        result = WebPageExtractor.extract_from_url('https://meucrm.com.br/planos')
        self.assertTrue(result['ok'])
        self.assertEqual(result['title'], 'Plano Pro CRM - Soluções Corporativas')
        self.assertIn('Plano Pro CRM', result['content'])
        self.assertIn('249 mensais', result['content'])
        self.assertNotIn("console.log('tracker')", result['content'])
        self.assertNotIn("Copyright 2026", result['content'])

    @patch('requests.get')
    def test_knowledge_add_website_endpoint(self, mock_get):
        """Testa a rota POST /admin/knowledge/website cadastrando um site na base de conhecimento."""
        fake_html = """
        <html><head><title>Sobre Nós - Empresa Alfa</title></head>
        <body><main><h1>Empresa Alfa</h1><p>Somos especialistas em consultoria técnica desde 2018.</p></main></body>
        </html>
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = fake_html
        mock_resp.encoding = 'utf-8'
        mock_get.return_value = mock_resp

        # Login como admin
        self.client.post('/auth/login', data={'username': 'admin_rag_web', 'password': 'senha123'})

        # Submete formulário de adição de site
        response = self.client.post('/admin/knowledge/website', data={
            'url': 'https://empresaalfa.com.br/sobre',
            'title': 'Institucional Empresa Alfa',
            'category': 'website'
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)

        # Verifica se gravou no banco de dados com doc_type='url'
        doc = KnowledgeDoc.query.filter_by(title='Institucional Empresa Alfa').first()
        self.assertIsNotNone(doc)
        self.assertEqual(doc.doc_type, 'url')
        self.assertEqual(doc.category, 'website')
        self.assertIn('Empresa Alfa', doc.content)

    def test_faq_miner_dialogues_and_storage(self):
        """Testa a coleta de pares conversacionais e armazenamento de FAQs minerados."""
        # Cria mensagens simuladas no MessageLog
        msg_in = MessageLog(
            chat_id='5511999998888@c.us',
            direction='inbound',
            status='received',
            content='Qual é o horário de atendimento no suporte?'
        )
        msg_out = MessageLog(
            chat_id='5511999998888@c.us',
            direction='outbound',
            status='sent',
            content='Nosso suporte atende de segunda a sexta das 08h às 18h via WhatsApp.'
        )
        db.session.add_all([msg_in, msg_out])
        db.session.commit()

        # Testa coleta
        dialogues = FAQMiner.collect_recent_dialogues(limit_messages=50)
        self.assertGreaterEqual(len(dialogues), 1)
        self.assertIn('horário de atendimento', dialogues[0]['question'].lower())

        # Testa persistência de FAQ
        synthetic_faqs = [{
            'title': 'FAQ: Horário de Atendimento do Suporte',
            'question': 'Qual é o horário de atendimento no suporte?',
            'answer': 'Nosso suporte atende de segunda a sexta das 08h às 18h via WhatsApp.',
            'tags': ['suporte', 'horário']
        }]

        saved = FAQMiner.save_and_index_faqs(synthetic_faqs, auto_index=False)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].category, 'faq')

        saved_doc = KnowledgeDoc.query.filter_by(title='FAQ: Horário de Atendimento do Suporte').first()
        self.assertIsNotNone(saved_doc)
        self.assertIn('segunda a sexta das 08h às 18h', saved_doc.content)

if __name__ == '__main__':
    unittest.main()
