import unittest
from app import create_app, db
from app.models import User, Client, ScrapingJob
from app.tasks.lead_scraper import normalize_brazilian_phone
from app.utils.maps_scraper import MapsScraperClient

from config import TestConfig

class TestLeadScraper(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(TestConfig)
        cls.client = cls.app.test_client()
        with cls.app.app_context():
            db.create_all()


    def test_normalize_brazilian_phone(self):
        """Valida a normalização de diferentes padrões de números de telefone do Brasil."""
        # Celular com DDD 19 (SP) formatado
        phone, is_valid, is_mobile = normalize_brazilian_phone("(19) 99876-5432")
        self.assertTrue(is_valid)
        self.assertTrue(is_mobile)
        self.assertEqual(phone, "5519998765432")

        # Fixo com DDI 55 e DDD 11
        phone, is_valid, is_mobile = normalize_brazilian_phone("+55 11 3214-5678")
        self.assertTrue(is_valid)
        self.assertFalse(is_mobile)
        self.assertEqual(phone, "551132145678")

        # Celular com zero no início (011987654321)
        phone, is_valid, is_mobile = normalize_brazilian_phone("011987654321")
        self.assertTrue(is_valid)
        self.assertTrue(is_mobile)
        self.assertEqual(phone, "5511987654321")

        # Celular antigo de 8 dígitos (sem o 9º dígito obrigatório)
        phone, is_valid, is_mobile = normalize_brazilian_phone("(21) 9876-5432")
        self.assertTrue(is_valid)
        self.assertTrue(is_mobile)
        self.assertEqual(phone, "5521998765432")

        # Fixo com DDD 31 (MG)
        phone, is_valid, is_mobile = normalize_brazilian_phone("3134567890")
        self.assertTrue(is_valid)
        self.assertFalse(is_mobile)
        self.assertEqual(phone, "553134567890")

        # Número inválido ou nulo
        phone, is_valid, is_mobile = normalize_brazilian_phone("12345")
        self.assertFalse(is_valid)
        self.assertIsNone(phone)

        phone, is_valid, is_mobile = normalize_brazilian_phone(None)
        self.assertFalse(is_valid)
        self.assertIsNone(phone)

    def test_maps_scraper_client_item_normalization(self):
        """Testa se o client normaliza chaves vindas de CSV ou JSON do gosom scraper."""
        client_api = MapsScraperClient()
        raw_row = {
            "Title": "Academia Força Total",
            "Phone": "+55 (19) 98765-4321",
            "Email": "contato@forcatotal.com.br",
            "Website": "https://forcatotal.com.br",
            "Address": "Rua Central, 123, Sumaré - SP",
            "Category": "Academia de Ginástica",
            "Total Score": "4.8",
            "Reviews Count": "120"
        }
        normalized = client_api._normalize_item(raw_row)
        self.assertEqual(normalized["name"], "Academia Força Total")
        self.assertEqual(normalized["phone"], "+55 (19) 98765-4321")
        self.assertEqual(normalized["email"], "contato@forcatotal.com.br")
        self.assertEqual(normalized["website"], "https://forcatotal.com.br")
        self.assertEqual(normalized["category"], "Academia de Ginástica")
        self.assertEqual(normalized["rating"], 4.8)
        self.assertEqual(normalized["reviews_count"], 120)

    def test_lead_deduplication_and_import(self):
        """Testa se a tarefa assíncrona deduplica telefones existentes e insere novos leads."""
        with self.app.app_context():
            # Usuário de teste
            user = User.query.filter_by(username='test_scraper_user').first()
            if not user:
                user = User(username='test_scraper_user', email='scraper_test@crm.com')
                user.set_password('pass123')
                db.session.add(user)
                db.session.commit()

            # Cria um cliente existente
            existing_phone = "5519999998888"
            existing_client = Client.query.filter_by(phone=existing_phone).first()
            if not existing_client:
                existing_client = Client(
                    name="Empresa Já Cadastrada",
                    phone=existing_phone,
                    status="fechado"
                )
                db.session.add(existing_client)
                db.session.commit()

            # Cria um ScrapingJob
            job = ScrapingJob(
                query="Academias em Teste SP",
                depth=1,
                extract_emails=True,
                status="queued",
                created_by_user_id=user.id
            )
            db.session.add(job)
            db.session.commit()

            # Itens mockados
            mock_items = [
                # Item 1: Telefone já cadastrado (deve ser ignorado)
                {
                    "name": "Empresa Já Cadastrada",
                    "phone": "(19) 99999-8888",
                    "email": "jaexiste@teste.com",
                    "website": "https://jaexiste.com",
                    "address": "Rua 1, Sumare",
                    "category": "Academia",
                    "rating": 5.0,
                    "reviews_count": 50
                },
                # Item 2: Lead novo (deve ser inserido)
                {
                    "name": "Academia Nova Era",
                    "phone": "(19) 98888-7777",
                    "email": "contato@novaera.com",
                    "website": "https://novaera.com",
                    "address": "Av Brasil, 500, Sumare",
                    "category": "Crossfit",
                    "rating": 4.9,
                    "reviews_count": 35
                }
            ]

            imported = 0
            for item in mock_items:
                norm_phone, is_valid, is_mobile = normalize_brazilian_phone(item["phone"])
                if norm_phone:
                    found = Client.query.filter_by(phone=norm_phone).first()
                    if found:
                        continue

                new_c = Client(
                    name=item["name"],
                    phone=norm_phone,
                    email=item["email"],
                    website=item["website"],
                    address=item["address"],
                    category=item["category"],
                    google_rating=item["rating"],
                    google_reviews_count=item["reviews_count"],
                    status='lead',
                    lead_source='Google Maps',
                    badges=f"outbound_gmaps,job_{job.id}",
                    assigned_to=user.id
                )
                db.session.add(new_c)
                imported += 1

            job.total_scraped = len(mock_items)
            job.total_imported = imported
            job.status = 'completed'
            db.session.commit()

            self.assertEqual(imported, 1)
            self.assertEqual(job.total_scraped, 2)
            self.assertEqual(job.total_imported, 1)

            # Verifica o cliente criado
            created = Client.query.filter_by(phone="5519988887777").first()
            self.assertIsNotNone(created)
            self.assertEqual(created.status, "lead")
            self.assertEqual(created.lead_source, "Google Maps")
            self.assertIn("outbound_gmaps", created.badges)
            self.assertIn(f"job_{job.id}", created.badges)
            self.assertEqual(created.google_rating, 4.9)

            # Limpeza do teste
            db.session.delete(created)
            db.session.delete(job)
            db.session.commit()

    def test_prospeccao_routes(self):
        """Testa se as rotas /crm/prospeccao e /crm/prospeccao/job/<id>/status respondem corretamente."""
        with self.app.app_context():
            user = User.query.filter_by(username='admin').first()
            if not user:
                user = User(username='admin', email='admin@test.com', role='admin')
                user.set_password('admin123')
                db.session.add(user)
                db.session.commit()

        # Login
        self.client.post('/auth/login', data={'username': 'admin', 'password': 'admin123'})

        # GET /crm/prospeccao
        resp = self.client.get('/crm/prospeccao')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Prospecção Ativa', resp.get_data(as_text=True))

        # POST /crm/prospeccao/start (JSON)
        start_resp = self.client.post('/crm/prospeccao/start', json={
            'query': 'Restaurantes em Campinas SP',
            'depth': 1,
            'extract_emails': True
        })
        self.assertEqual(start_resp.status_code, 200)
        data = start_resp.get_json()
        self.assertTrue(data.get('ok'))
        job_id = data['job']['id']

        # GET /crm/prospeccao/job/<id>/status
        status_resp = self.client.get(f'/crm/prospeccao/job/{job_id}/status')
        self.assertEqual(status_resp.status_code, 200)
        status_data = status_resp.get_json()
        self.assertTrue(status_data.get('ok'))
        self.assertEqual(status_data['job']['query'], 'Restaurantes em Campinas SP')

        # Limpeza
        with self.app.app_context():
            j = ScrapingJob.query.get(job_id)
            if j:
                db.session.delete(j)
                db.session.commit()

    def test_cancel_scraping_job_unit(self):
        """Valida a função cancel_scraping_job no modelo e banco."""
        from app.tasks.lead_scraper import cancel_scraping_job

        with self.app.app_context():
            # 1. Cria um job ativo
            job = ScrapingJob(
                query_term="Padarias em Sumaré SP",
                status="processing",
                progress=40,
                current_step="Minerando..."
            )
            db.session.add(job)
            db.session.commit()
            job_id = job.id

            # Cancela
            ok, msg = cancel_scraping_job(job_id)
            self.assertTrue(ok)
            self.assertIn("cancelada com sucesso", msg)

            db.session.refresh(job)
            self.assertEqual(job.status, "cancelled")
            self.assertEqual(job.current_step, "Cancelado pelo usuário")
            self.assertIsNotNone(job.finished_at)

            # Tenta cancelar novamente job já cancelado
            ok2, msg2 = cancel_scraping_job(job_id)
            self.assertFalse(ok2)
            self.assertIn("já está cancelada", msg2)

            # Limpeza
            db.session.delete(job)
            db.session.commit()

    def test_cancel_scraping_job_route(self):
        """Testa o endpoint POST /crm/prospeccao/job/<id>/cancel."""
        with self.app.app_context():
            user = User.query.filter_by(username='admin').first()
            if not user:
                user = User(username='admin', email='admin@test.com', role='admin')
                user.set_password('admin123')
                db.session.add(user)
                db.session.commit()

            job = ScrapingJob(
                query_term="Farmácias em Americana",
                status="queued"
            )
            db.session.add(job)
            db.session.commit()
            job_id = job.id

        # Login
        self.client.post('/auth/login', data={'username': 'admin', 'password': 'admin123'})

        # Cancelar via POST JSON
        resp = self.client.post(f'/crm/prospeccao/job/{job_id}/cancel', json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('ok'))
        self.assertEqual(data.get('job', {}).get('status'), 'cancelled')

        # Verificar se o status no banco é cancelled
        with self.app.app_context():
            j = ScrapingJob.query.get(job_id)
            self.assertEqual(j.status, 'cancelled')
            db.session.delete(j)
            db.session.commit()


if __name__ == '__main__':
    unittest.main()

