import unittest
from app import create_app, db
from app.models import Client, User
from app.utils.lead_enricher import LeadEnricher
from config import TestConfig

class LeadEnricherTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_phone_cleaning_and_formatting(self):
        # 13 dígitos com DDI 55
        self.assertEqual(LeadEnricher.clean_digits("5519998306652@c.us"), "5519998306652")
        self.assertEqual(LeadEnricher.format_phone_display("5519998306652@c.us"), "(19) 99830-6652")

        # 11 dígitos
        self.assertEqual(LeadEnricher.format_phone_display("11987654321"), "(11) 98765-4321")

        # 10 dígitos (fixo)
        self.assertEqual(LeadEnricher.format_phone_display("1932345678"), "(19) 3234-5678")

        # 12 dígitos (celular sem o 9 no Brasil)
        self.assertEqual(LeadEnricher.format_phone_display("551998306652"), "(19) 99830-6652")

    def test_extract_clean_push_name(self):
        self.assertEqual(LeadEnricher.extract_clean_push_name("Carlos Eduardo"), "Carlos Eduardo")
        self.assertEqual(LeadEnricher.extract_clean_push_name("Ana Paula | Consultora"), "Ana Paula")
        self.assertEqual(LeadEnricher.extract_clean_push_name("Marcio - Tech"), "Marcio")
        
        # Casos inválidos
        self.assertIsNone(LeadEnricher.extract_clean_push_name(None))
        self.assertIsNone(LeadEnricher.extract_clean_push_name("5519998306652"))
        self.assertIsNone(LeadEnricher.extract_clean_push_name("."))
        self.assertIsNone(LeadEnricher.extract_clean_push_name("😊👍"))

    def test_extract_entities_from_text(self):
        # Extração de Nome
        text1 = "Olá, meu nome é Roberto Carlos e gostaria de informações"
        ent1 = LeadEnricher.extract_entities_from_text(text1)
        self.assertEqual(ent1.get('name'), "Roberto Carlos")

        # Extração de Nome direto com resposta à pergunta do bot
        ent_asked = LeadEnricher.extract_entities_from_text(
            text="Juliana Mendes",
            last_assistant_message="Olá! Como posso te chamar?"
        )
        self.assertEqual(ent_asked.get('name'), "Juliana Mendes")

        # Extração de E-mail
        text2 = "Pode me enviar a proposta no email carlos.silva@empresa.com.br por favor"
        ent2 = LeadEnricher.extract_entities_from_text(text2)
        self.assertEqual(ent2.get('email'), "carlos.silva@empresa.com.br")

        # Extração de Segmento
        text3 = "Sou proprietário de uma clínica odontológica aqui em Campinas"
        ent3 = LeadEnricher.extract_entities_from_text(text3)
        self.assertIn("Clínica", ent3.get('segment'))

    def test_find_client_by_phone_and_enrichment(self):
        # Cria cliente inicial no banco com telefone formatado
        client = Client(
            name="Lead WA 6652",
            phone="(19) 99830-6652",
            status="lead"
        )
        db.session.add(client)
        db.session.commit()

        # Busca pelo formato JID do WhatsApp
        found = LeadEnricher.find_client_by_phone("5519998306652@c.us")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, client.id)

        # Enriquecimento com nome e e-mail
        new_data = {
            "name": "Carlos Eduardo Silva",
            "email": "carlos@empresa.com.br",
            "segment": "Varejo e Comércio"
        }
        updated = LeadEnricher.enrich_client_record(found, new_data)
        self.assertTrue(updated)

        # Verifica persistência
        refreshed = Client.query.get(client.id)
        self.assertEqual(refreshed.name, "Carlos Eduardo Silva")
        self.assertEqual(refreshed.email, "carlos@empresa.com.br")
        self.assertEqual(refreshed.segment, "Varejo e Comércio")
        self.assertEqual(refreshed.status, "contato")

        # Garante que dados existentes NÃO são apagados se nova extração vier vazia
        empty_data = {"name": None, "email": None}
        LeadEnricher.enrich_client_record(refreshed, empty_data)
        after_empty = Client.query.get(client.id)
        self.assertEqual(after_empty.name, "Carlos Eduardo Silva")
        self.assertEqual(after_empty.email, "carlos@empresa.com.br")

    def test_build_qualification_prompt_context(self):
        client = Client(name="Lead WA 1234", phone="(11) 98888-1234", status="lead")
        context_str = LeadEnricher.build_qualification_prompt_context(client)
        self.assertIn("QUALIFICAÇÃO EM ANDAMENTO", context_str)
        self.assertIn("Nome do cliente", context_str)
        self.assertIn("DIRETRIZ DE COLETA ATIVA DE DADOS", context_str)

if __name__ == '__main__':
    unittest.main()
