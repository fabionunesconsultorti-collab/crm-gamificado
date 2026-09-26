import unittest
import json
from app import create_app, db
from app.models import User, Setting, KnowledgeDoc
from app.utils.rag_engine import RAGEngine

class TestRAGAdvanced(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            # Cria admin de teste
            self.admin = User(username='admin_rag', email='admin_rag@crm.com', role='admin')
            self.admin.set_password('senha123')
            db.session.add(self.admin)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_bm25_scoring(self):
        """Testa o cálculo léxico de BM25 em queries exatas."""
        doc = "Tabela de Preços: O Plano Pro custa R$ 249 por mês e inclui automação."
        score_exact = RAGEngine.calculate_bm25_score("Plano Pro 249", doc)
        score_unrelated = RAGEngine.calculate_bm25_score("receita de bolo de chocolate", doc)

        self.assertGreater(score_exact, 0.2)
        self.assertEqual(score_unrelated, 0.0)

    def test_rag_configs_defaults_and_override(self):
        """Testa a leitura de defaults e override de configurações dinâmicas."""
        with self.app.app_context():
            configs = RAGEngine.get_all_configs()
            self.assertEqual(configs['rag_chunk_size'], 450)
            self.assertEqual(configs['rag_search_mode'], 'hybrid')
            self.assertEqual(configs['rag_hybrid_alpha'], 0.70)

            # Override via Setting
            Setting.set_val('rag_chunk_size', '600')
            Setting.set_val('rag_hybrid_alpha', '0.85')
            db.session.commit()

            new_configs = RAGEngine.get_all_configs()
            self.assertEqual(new_configs['rag_chunk_size'], 600)
            self.assertEqual(new_configs['rag_hybrid_alpha'], 0.85)

    def test_chunking_strategies(self):
        """Testa as estratégias de fatiamento (paragraph, sentence, fixed)."""
        text = "Primeiro bloco longo.\n\nSegundo bloco longo.\n\nTerceiro bloco longo."
        chunks_para = RAGEngine.chunk_text(text, chunk_size=50, overlap=10, strategy='paragraph')
        self.assertGreaterEqual(len(chunks_para), 2)

    def test_calibrate_endpoints(self):
        """Testa a rota de calibração via API logada como admin."""
        # Login
        self.client.post('/auth/login', data={'username': 'admin_rag', 'password': 'senha123'})

        # Salva nova calibração
        payload = {
            'rag_chunk_size': '520',
            'rag_hybrid_alpha': '0.65',
            'rag_search_mode': 'hybrid',
            'rag_top_k': '10',
            'whatsapp_bot_temperature': '0.20'
        }
        res = self.client.post('/admin/knowledge/calibrate', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['configs']['rag_chunk_size'], 520)
        self.assertEqual(data['configs']['rag_hybrid_alpha'], 0.65)
        self.assertEqual(data['configs']['whatsapp_bot_temperature'], 0.20)

        # Testa Reset de Calibração
        res_reset = self.client.post('/admin/knowledge/calibrate/reset', json={})
        self.assertEqual(res_reset.status_code, 200)
        reset_data = res_reset.get_json()
        self.assertTrue(reset_data['ok'])
        self.assertEqual(reset_data['configs']['rag_chunk_size'], 450)
        self.assertEqual(reset_data['configs']['rag_hybrid_alpha'], 0.70)

    def test_telemetry_endpoint(self):
        """Testa o endpoint de telemetria do RAG."""
        self.client.post('/auth/login', data={'username': 'admin_rag', 'password': 'senha123'})
        res = self.client.get('/admin/knowledge/telemetry')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('total_queries', data)
        self.assertIn('avg_latency_ms', data)
        self.assertIn('hit_rate_pct', data)

if __name__ == '__main__':
    unittest.main()
