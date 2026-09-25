import unittest
from app import create_app, db
from app.models import User, Client, Store
from config import TestConfig

class TestCRMSearchAndFilters(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Usuários e loja de teste
        self.user1 = User(username='vendedor_carlos', role='vendedor')
        self.user1.set_password('123')
        self.user2 = User(username='vendedora_ana', role='vendedor')
        self.user2.set_password('123')
        db.session.add_all([self.user1, self.user2])
        db.session.commit()

        self.store = Store(name='Loja Jardins')
        db.session.add(self.store)
        db.session.commit()

        # Criação de leads com atributos variados
        c1 = Client(
            name='Padaria Central',
            phone='(11) 98888-1111',
            email='contato@padariacentral.com.br',
            cpf='12.345.678/0001-90',
            segment='Padaria',
            status='lead',
            assigned_to=self.user1.id,
            tier='bronze',
            lead_source='loja_fisica',
            badges='cliente_recorrente'
        )
        c2 = Client(
            name='Clínica Odonto Sorriso',
            phone='(11) 97777-2222',
            email='financeiro@odontosorriso.com',
            cpf='98.765.432/0001-10',
            segment='Saúde / Odonto',
            status='proposta',
            assigned_to=self.user2.id,
            tier='vip',
            lead_source='gmaps',
            badges='outbound_gmaps'
        )
        c3 = Client(
            name='João da Silva Restaurante',
            phone='(21) 96666-3333',
            email='joao@restaurante.com',
            cpf='111.222.333-44',
            segment='Restaurante',
            status='fechado',
            assigned_to=self.user1.id,
            tier='ouro',
            lead_source='indicacao'
        )
        db.session.add_all([c1, c2, c3])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.user1.id)
            sess['_fresh'] = True

    def test_list_clients_smart_search_by_name_and_segment(self):
        self._login()

        # Busca por nome
        res = self.client.get('/crm/clients?q=Padaria')
        self.assertEqual(res.status_code, 200)
        self.assertIn('Padaria Central', res.get_data(as_text=True))
        self.assertNotIn('Clínica Odonto Sorriso', res.get_data(as_text=True))

        # Busca por e-mail
        res2 = self.client.get('/crm/clients?q=odontosorriso.com')
        self.assertEqual(res2.status_code, 200)
        self.assertIn('Clínica Odonto Sorriso', res2.get_data(as_text=True))
        self.assertNotIn('João da Silva Restaurante', res2.get_data(as_text=True))

        # Busca por telefone
        res3 = self.client.get('/crm/clients?q=96666-3333')
        self.assertEqual(res3.status_code, 200)
        self.assertIn('João da Silva Restaurante', res3.get_data(as_text=True))

    def test_list_clients_filters_by_attributes(self):
        self._login()

        # Filtro por status
        res_status = self.client.get('/crm/clients?status=proposta')
        self.assertEqual(res_status.status_code, 200)
        self.assertIn('Clínica Odonto Sorriso', res_status.get_data(as_text=True))
        self.assertNotIn('Padaria Central', res_status.get_data(as_text=True))

        # Filtro por vendedor responsável
        res_seller = self.client.get(f'/crm/clients?seller_id={self.user2.id}')
        self.assertEqual(res_seller.status_code, 200)
        self.assertIn('Clínica Odonto Sorriso', res_seller.get_data(as_text=True))
        self.assertNotIn('Padaria Central', res_seller.get_data(as_text=True))

        # Filtro por tier
        res_tier = self.client.get('/crm/clients?tier=vip')
        self.assertEqual(res_tier.status_code, 200)
        self.assertIn('Clínica Odonto Sorriso', res_tier.get_data(as_text=True))

    def test_kanban_search_and_filters(self):
        self._login()

        # Kanban com busca
        res_kanban_search = self.client.get('/crm/kanban?q=Padaria')
        self.assertEqual(res_kanban_search.status_code, 200)
        self.assertIn('Padaria Central', res_kanban_search.get_data(as_text=True))
        self.assertNotIn('Clínica Odonto Sorriso', res_kanban_search.get_data(as_text=True))

        # Kanban com filtro por segmento
        res_kanban_seg = self.client.get('/crm/kanban?segment=Restaurante')
        self.assertEqual(res_kanban_seg.status_code, 200)
        self.assertIn('João da Silva Restaurante', res_kanban_seg.get_data(as_text=True))
        self.assertNotIn('Padaria Central', res_kanban_seg.get_data(as_text=True))

if __name__ == '__main__':
    unittest.main()
