import unittest
from app import create_app, db
from app.models import User, Client, IntegrationConfig, ExternalEntityMap, BlingSalesCache, IntegrationLog, BlingProductCache
from app.integrations.manager import IntegrationManager
from app.integrations.bling.adapter import BlingAdapter
from config import TestConfig

class BlingIntegrationTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Cria usuário admin de teste
        self.admin = User(username='admin_test', email='admin@test.com', role='admin')
        self.admin.set_password('password')
        db.session.add(self.admin)
        db.session.commit()

        # Reseta configuração do Bling no banco
        cfg = IntegrationConfig.query.filter_by(provider='bling').first()
        if cfg:
            db.session.delete(cfg)
            db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_integration_manager_registration(self):
        """Verifica se o BlingAdapter é registrado automaticamente no IntegrationManager."""
        adapter = IntegrationManager.get_adapter('bling')
        self.assertIsNotNone(adapter)
        self.assertEqual(adapter.provider_name, 'bling')
        self.assertEqual(adapter.display_name, 'Bling ERP')

    def test_default_inactive_state(self):
        """Verifica se a integração inicia desativada (Feature Flag OFF) por padrão."""
        adapter = IntegrationManager.get_adapter('bling')
        self.assertFalse(adapter.is_enabled())

    def test_toggle_integration(self):
        """Testa ligar (ON) e desligar (OFF) a integração via IntegrationManager."""
        res_on = IntegrationManager.toggle_integration('bling', True)
        self.assertTrue(res_on['success'])
        self.assertTrue(res_on['is_active'])

        adapter = IntegrationManager.get_adapter('bling')
        self.assertTrue(adapter.is_enabled())

        res_off = IntegrationManager.toggle_integration('bling', False)
        self.assertTrue(res_off['success'])
        self.assertFalse(res_off['is_active'])
        self.assertFalse(adapter.is_enabled())

    def test_update_config(self):
        """Testa atualização de credenciais (Client ID, Access Token, API Key)."""
        res = IntegrationManager.update_config('bling', {
            'auth_type': 'oauth2',
            'client_id': 'bling_client_123',
            'client_secret': 'bling_secret_456',
            'access_token': 'test_token_abc'
        })
        self.assertTrue(res['success'])

        cfg = IntegrationConfig.query.filter_by(provider='bling').first()
        self.assertEqual(cfg.client_id, 'bling_client_123')
        self.assertEqual(cfg.client_secret, 'bling_secret_456')
        self.assertEqual(cfg.access_token, 'test_token_abc')

    def test_inbound_outbound_when_disabled(self):
        """Verifica se chamadas de sync retornam aviso quando a integração estiver desativada."""
        adapter = IntegrationManager.get_adapter('bling')
        res_in = adapter.sync_clients_inbound()
        self.assertFalse(res_in['success'])
        self.assertIn('desativada', res_in['message'])

        res_out = adapter.sync_clients_outbound()
        self.assertFalse(res_out['success'])
        self.assertIn('desativada', res_out['message'])

    def test_external_entity_map_and_sales_cache(self):
        """Testa o modelo de mapeamento de entidades externas e cache de vendas."""
        client = Client(name='Cliente Teste Bling', phone='19999998888', cpf='12345678901')
        db.session.add(client)
        db.session.commit()

        # Cria mapeamento externo
        mapping = ExternalEntityMap(
            provider='bling',
            crm_entity_type='client',
            crm_entity_id=client.id,
            external_id='987654321',
            sync_status='synced'
        )
        db.session.add(mapping)

        # Cria pedido no cache
        sales_cache = BlingSalesCache(
            bling_order_id='ORD-1001',
            order_number='1001',
            client_cpf_cnpj='12345678901',
            client_name='Cliente Teste Bling',
            total_value=250.50,
            status='Atendido'
        )
        db.session.add(sales_cache)
        db.session.commit()

        # Assertions
        saved_map = ExternalEntityMap.query.filter_by(external_id='987654321').first()
        self.assertIsNotNone(saved_map)
        self.assertEqual(saved_map.crm_entity_id, client.id)

        saved_sales = BlingSalesCache.query.filter_by(bling_order_id='ORD-1001').first()
        self.assertIsNotNone(saved_sales)
        self.assertEqual(saved_sales.total_value, 250.50)

    def test_webhook_event_processing(self):
        """Testa o recebimento e processamento de eventos de Webhook do Bling."""
        IntegrationManager.toggle_integration('bling', True)
        adapter = IntegrationManager.get_adapter('bling')

        # Teste evento de estoque/produto
        res_stock = adapter.process_webhook_event({
            "event": "estoques.atualizado",
            "data": {"id": 888999}
        })
        self.assertTrue(res_stock['success'])
        self.assertEqual(res_stock['event'], 'estoques.atualizado')

        # Verifica se o log foi gravado no banco
        log = IntegrationLog.query.filter_by(action='webhook_stock_update').first()
        self.assertIsNotNone(log)
        self.assertIn('888999', log.details)

    def test_decision_reports_generation(self):
        """Testa a geração dos relatórios para tomada de decisão no BlingAdapter."""
        IntegrationManager.toggle_integration('bling', True)
        adapter = IntegrationManager.get_adapter('bling')

        # Popula produto de teste no cache
        prod = BlingProductCache(
            bling_product_id="TEST-100",
            code="PRD-100",
            name="Produto Teste Real",
            brand="Nike",
            supplier_name="Distribuidor Alfa",
            category="Vestuário",
            size="M",
            price=150.0,
            cost_price=50.0,
            current_stock=10,
            days_without_sale=45
        )
        db.session.add(prod)
        db.session.commit()

        data = adapter.get_decision_reports_data({'min_days': '0'})
        self.assertIn('stock_report', data)
        self.assertIn('clients_report', data)
        self.assertIn('size_report', data)
        self.assertIn('size_products_report', data)
        self.assertGreater(len(data['stock_report']), 0)
        self.assertEqual(data['stock_report'][0]['code'], 'PRD-100')

    def test_toggle_off_purges_cache(self):
        """Verifica se inativar a integração limpa o cache local de vendas e produtos do Bling."""
        IntegrationManager.toggle_integration('bling', True)
        
        # Adiciona item de cache
        prod = BlingProductCache(bling_product_id="TEST-999", name="Produto Cache Teste", price=100.0)
        sale = BlingSalesCache(bling_order_id="SALE-999", order_number="999", total_value=100.0)
        db.session.add(prod)
        db.session.add(sale)
        db.session.commit()

        self.assertEqual(BlingProductCache.query.count(), 1)
        self.assertEqual(BlingSalesCache.query.count(), 1)

        # Inativa a integração
        res = IntegrationManager.toggle_integration('bling', False)
        self.assertTrue(res['success'])
        self.assertFalse(res['is_active'])

        # Verifica se o cache foi completamente limpo
        self.assertEqual(BlingProductCache.query.count(), 0)
        self.assertEqual(BlingSalesCache.query.count(), 0)

if __name__ == '__main__':
    unittest.main()


