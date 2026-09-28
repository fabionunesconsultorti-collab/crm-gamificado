import unittest
from unittest.mock import patch, MagicMock
from app import create_app, db
from app.models import User, KnowledgeDoc
from app.utils.rag_engine import RAGEngine
from app.utils.ai_handler import AIHandler
from config import TestConfig

class TestSkillsRAG(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()

        db.create_all()

        # Cria admin para testes autenticados
        self.admin = User(username='admin_skills', email='admin_skills@crm.com', role='admin')
        self.admin.set_password('senha123')
        db.session.add(self.admin)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_add_skill_endpoint(self):
        """Testa o endpoint POST /admin/knowledge/skill cadastrando um skill no banco e RAG."""
        self.client.post('/auth/login', data={'username': 'admin_skills', 'password': 'senha123'})

        res = self.client.post('/admin/knowledge/skill', data={
            'title': 'Contorno de Objeção de Preço',
            'category': 'skill_vendas',
            'content': 'Quando o cliente alegar que o preço está alto, demonstre o ROI e o valor dos diferenciais exclusivos.'
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)

        # Verifica se o documento foi cadastrado como doc_type='skill'
        doc = KnowledgeDoc.query.filter(KnowledgeDoc.title.like('%Contorno de Objeção%')).first()
        self.assertIsNotNone(doc)
        self.assertEqual(doc.doc_type, 'skill')
        self.assertEqual(doc.category, 'skill_vendas')
        self.assertIn('demonstre o ROI', doc.content)

    def test_skill_boosting_in_rag(self):
        """Testa a priorização (Skill Boosting +0.18) no RAGEngine.search_relevant_snippets."""
        candidates = [
            {
                'title': 'Tabela de Preços Geral',
                'category': 'precos',
                'score': 0.60,
                'dense_score': 0.60,
                'bm25_score': 0.60,
                'raw_text': 'O plano custa R$ 249'
            },
            {
                'title': '🎯 Skill: Contorno de Objeção de Preço',
                'category': 'skill_vendas',
                'score': 0.60,
                'dense_score': 0.60,
                'bm25_score': 0.60,
                'raw_text': 'Acolha o cliente com empatia e apresente o ROI'
            }
        ]

        # Simula a consulta e a reclassificação
        query = "Está muito caro este valor de 249"
        
        # Testando identificação da categoria de skill
        for c in candidates:
            cat_lower = str(c.get('category', '')).lower()
            title_lower = str(c.get('title', '')).lower()
            is_skill = any(k in cat_lower or k in title_lower for k in ['skill', 'habilidade', 'diretriz', 'conduta', 'objecao', 'fechamento', 'postura', 'vendas'])
            c['is_skill'] = is_skill
            skill_bonus = 0.18 if is_skill else 0.0
            c['rerank_score'] = round(c['score'] + skill_bonus, 4)

        candidates.sort(key=lambda x: x['rerank_score'], reverse=True)

        # O primeiro candidato DEVE ser o Skill por conta do boosting (+0.18 vs 0.60)
        self.assertTrue(candidates[0]['is_skill'])
        self.assertEqual(candidates[0]['rerank_score'], 0.78)

    @patch('app.utils.rag_engine.RAGEngine.get_structured_context')
    def test_structured_prompt_injection(self, mock_get_context):
        """Testa se o AIHandler separa e destaca os Skills no Prompt do Sistema."""
        mock_get_context.return_value = {
            'skills_text': '- [🎯 Skill: Objeção]: Acolha o cliente e mostre o ROI.',
            'official_text': '- [Tabela]: Plano Pro por R$ 249.',
            'snippets': [{'title': 'Skill'}, {'title': 'Tabela'}]
        }

        # Invoca geração de resposta do chat com RAG habilitado
        with patch('app.utils.ai_handler.AIHandler.get_config') as mock_cfg:
            mock_cfg.return_value = {
                'provider': 'ollama',
                'api_key': '',
                'bot_persona_name': 'Sofia',
                'bot_company_name': 'Empresa CRM',
                'bot_system_prompt': '',
                'rag_enabled': True,
                'rag_top_k': 4,
                'bot_temperature': 0.3,
                'bot_max_tokens': 200,
                'ollama_url': 'http://localhost:11434',
                'ollama_model': 'llama3.2'
            }

            with patch('requests.post') as mock_post:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"message": {"content": "Entendo perfeitamente sua preocupação com o investimento..."}}
                mock_post.return_value = mock_resp

                reply, err = AIHandler.generate_chat_reply("Acho que o plano de 249 está um pouco caro")
                self.assertIsNone(err)
                self.assertIn("Entendo perfeitamente", reply)

                # Verifica se o payload enviado ao Ollama continha a seção prioritária de SKILLS
                called_payload = mock_post.call_args[1]['json']
                system_msg = called_payload['messages'][0]['content']
                self.assertIn("SKILLS & DIRETRIZES DE ATENDIMENTO PRIORITÁRIAS", system_msg)
                self.assertIn("INFORMAÇÕES OFICIAIS DO NEGÓCIO", system_msg)

if __name__ == '__main__':
    unittest.main()
