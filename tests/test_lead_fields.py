import unittest
from app import create_app, db
from app.models import User, Client
from app.utils.maps_scraper import MapsScraperClient

class TestLeadFields(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = cls.app.test_client()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    def test_client_model_cpf_cnpj_segment_and_social(self):
        """Valida que o modelo Client aceita CPF, CNPJ, Segmento, Instagram e Website."""
        # 1. Lead com CNPJ formatado (18 caracteres)
        cnpj_lead = Client(
            name="Empresa Alfa Ltda",
            phone="5519999990001",
            cpf="12.345.678/0001-95", # 18 chars
            segment="Tecnologia da Informação",
            instagram="@empresa_alfa",
            website="empresaalfa.com.br"
        )
        self.assertEqual(cnpj_lead.cpf, "12.345.678/0001-95")
        self.assertEqual(cnpj_lead.display_segment, "Tecnologia da Informação")
        self.assertEqual(cnpj_lead.instagram_url, "https://instagram.com/empresa_alfa")
        self.assertEqual(cnpj_lead.website_url, "https://empresaalfa.com.br")

        # 2. Lead com CPF formatado (14 caracteres)
        cpf_lead = Client(
            name="João Pessoa Física",
            phone="5519999990002",
            cpf="123.456.789-01",
            category="Consultoria",
            instagram="https://instagram.com/joao_consultor",
            website="https://joaoconsultor.com"
        )
        self.assertEqual(cpf_lead.cpf, "123.456.789-01")
        # Deve fazer fallback para category se segment não foi preenchido
        self.assertEqual(cpf_lead.display_segment, "Consultoria")
        self.assertEqual(cpf_lead.instagram_url, "https://instagram.com/joao_consultor")
        self.assertEqual(cpf_lead.website_url, "https://joaoconsultor.com")

    def test_maps_scraper_normalizes_instagram_and_segment(self):
        """Valida que o MapsScraperClient extrai corretamente categoria/segmento e Instagram."""
        client_api = MapsScraperClient()

        # Caso onde website é na verdade o Instagram do estabelecimento (muito comum no Google Maps)
        raw_row = {
            "title": "Padaria Silva",
            "phone": "(19) 3873-1495",
            "category": "Padaria Artesanal",
            "website": "https://www.instagram.com/panificadora.silva/",
            "total_score": "4.6",
            "reviews_count": "400"
        }
        normalized = client_api._normalize_item(raw_row)
        self.assertEqual(normalized["category"], "Padaria Artesanal")
        self.assertEqual(normalized["instagram"], "https://www.instagram.com/panificadora.silva/")
        self.assertEqual(normalized["website"], "https://www.instagram.com/panificadora.silva/")

    def test_create_and_edit_client_with_new_fields(self):
        """Valida criação e edição de cliente via rotas do CRM com os novos campos."""
        # Garante usuário para login
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(username='admin', email='admin@test.com', role='admin')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()

        # Login
        self.client.post('/auth/login', data={'username': 'admin', 'password': 'admin123'})

        unique_phone = "5519988887777"
        unique_cnpj = "99.888.777/0001-66"

        # Remove existente se houver
        existing = Client.query.filter((Client.phone == unique_phone) | (Client.cpf == unique_cnpj)).all()
        for ex in existing:
            db.session.delete(ex)
        db.session.commit()

        # Criação
        resp = self.client.post('/crm/client/new', data={
            'name': 'Padaria & Confeitaria Exemplo',
            'phone': unique_phone,
            'cpf': unique_cnpj,
            'email': 'contato@padariaexemplo.com',
            'segment': 'Panificação e Confeitaria',
            'instagram': '@padaria_exemplo',
            'website': 'https://padariaexemplo.com.br',
            'status': 'lead'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        created = Client.query.filter_by(phone=unique_phone).first()
        self.assertIsNotNone(created)
        self.assertEqual(created.cpf, unique_cnpj)
        self.assertEqual(created.segment, 'Panificação e Confeitaria')
        self.assertEqual(created.instagram, '@padaria_exemplo')
        self.assertEqual(created.website, 'https://padariaexemplo.com.br')
        self.assertEqual(created.instagram_url, 'https://instagram.com/padaria_exemplo')

        # Edição
        resp_edit = self.client.post(f'/crm/client/{created.id}/edit', data={
            'name': 'Padaria & Confeitaria Exemplo Atualizada',
            'phone': unique_phone,
            'cpf': unique_cnpj,
            'email': 'novo@padariaexemplo.com',
            'segment': 'Alimentos e Bebidas',
            'instagram': 'padaria_atualizada',
            'website': 'www.novopadaria.com.br',
            'status': 'contato'
        }, follow_redirects=True)
        self.assertEqual(resp_edit.status_code, 200)

        updated = Client.query.get(created.id)
        self.assertEqual(updated.name, 'Padaria & Confeitaria Exemplo Atualizada')
        self.assertEqual(updated.segment, 'Alimentos e Bebidas')
        self.assertEqual(updated.instagram, 'padaria_atualizada')
        self.assertEqual(updated.website, 'www.novopadaria.com.br')
        self.assertEqual(updated.website_url, 'https://www.novopadaria.com.br')
        self.assertEqual(updated.instagram_url, 'https://instagram.com/padaria_atualizada')

        # Limpeza
        db.session.delete(updated)
        db.session.commit()
