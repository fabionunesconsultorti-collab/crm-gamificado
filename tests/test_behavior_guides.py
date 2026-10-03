import unittest
import io
from app import create_app, db
from app.models import User, BehaviorGuide, WahaInstance, KnowledgeDoc
from app.utils.behavior_parser import BehaviorParser
from config import TestConfig

SAMPLE_MARKDOWN = '''---
name: Playbook Odonto Premium
niche: Odontologia Estetica
version: 1.2.0
target_audience: Pacientes particulares
communication_style: Empatico e acolhedor
persona_name: Camila
company_name: Sorriso Radiante
---

# Guia de Atendimento Odontologico

## 1. Persona e Tom
Voce e a Camila da Clinica Sorriso Radiante.

## 2. Arvore de Decisao
- Se perguntar preco: Convide para avaliacao presencial.
- Se relatar dor: Encaixe prioritario.

## 8. Bloco de Contexto Estruturado (System Prompt)
Voce e a Camila, consultora da Clinica Sorriso Radiante.
Responda com no maximo 1 a 2 frases curtas e objetivas.
[PAUSAR_ATENDIMENTO] Se a duvida for complexa, pause para transbordo.
'''

class TestBehaviorGuides(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.user = User(username='admin_test', role='admin')
        self.user.set_password('123456')
        db.session.add(self.user)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.user.id)
            sess['_fresh'] = True

    def test_parse_markdown_and_metadata(self):
        parsed = BehaviorParser.parse_markdown(SAMPLE_MARKDOWN, filename="playbook_odonto.md")
        self.assertEqual(parsed['niche'], "Odontologia Estetica")
        self.assertEqual(parsed['persona_name'], "Camila")
        self.assertEqual(parsed['company_name'], "Sorriso Radiante")
        self.assertIn("[PAUSAR_ATENDIMENTO]", parsed['system_prompt'])
        self.assertTrue(len(parsed['sections']) >= 2)

    def test_save_and_activate_guide(self):
        guide, parsed = BehaviorParser.save_guide_from_content(SAMPLE_MARKDOWN, filename="odonto.md", is_active=True)
        self.assertIsNotNone(guide.id)
        self.assertTrue(guide.is_active)
        self.assertEqual(guide.niche, "Odontologia Estetica")

        # Test resolution
        resolved = BehaviorParser.get_guide_for_context()
        self.assertEqual(resolved.id, guide.id)

    def test_instance_level_guide_binding(self):
        # Guide 1: Global
        g_global, _ = BehaviorParser.save_guide_from_content(SAMPLE_MARKDOWN, filename="global.md", is_active=True)

        # Guide 2: Instance specific
        custom_md = SAMPLE_MARKDOWN.replace("Odontologia Estetica", "Imobiliaria VIP")
        g_instance, _ = BehaviorParser.save_guide_from_content(custom_md, filename="imob.md", is_active=False)

        # Setup WahaInstance
        inst = WahaInstance(name="WhatsApp Vendas", session_name="wa_vendas", behavior_guide_id=g_instance.id)
        db.session.add(inst)
        db.session.commit()

        # Without instance_id -> receives global guide
        self.assertEqual(BehaviorParser.get_guide_for_context().id, g_global.id)

        # With instance_id -> receives instance dedicated guide
        self.assertEqual(BehaviorParser.get_guide_for_context(instance_id=inst.id).id, g_instance.id)

    def test_admin_panel_get_and_upload(self):
        self._login()
        resp = self.client.get('/admin/behavior-guides')
        self.assertEqual(resp.status_code, 200)

        # Test upload
        data = {
            'file': (io.BytesIO(SAMPLE_MARKDOWN.encode('utf-8')), 'novo_playbook.md'),
            'activate_now': '1'
        }
        post_resp = self.client.post('/admin/behavior-guides/upload', data=data, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(post_resp.status_code, 200)

        guide = BehaviorGuide.query.filter_by(slug='guia_de_atendimento_odontologico').first()
        self.assertIsNotNone(guide)
        self.assertTrue(guide.is_active)
