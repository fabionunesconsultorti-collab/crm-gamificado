import unittest
import json
from datetime import datetime, timedelta
from app import create_app, db
from app.models import User, Client, MessageLog, WahaInstance, BulkCampaign, BulkCampaignRecipient, Setting
from app.tasks.bulk_engine import (
    resolve_spintax, resolve_message_variables, get_time_greeting,
    is_master_switch_enabled, set_master_switch,
    start_campaign_engine, pause_campaign_engine, cancel_campaign_engine
)
from app.crm.routes import build_client_filter_query


class TestBulkEngine(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.client = self.app.test_client()

        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Cria usuário admin
        self.user = User(username='test_admin', email='test@crm.com', role='admin')
        self.user.set_password('123456')
        db.session.add(self.user)

        # Cria instância WAHA com anti-ban
        self.instance = WahaInstance(
            name='Test Server',
            session_name='default',
            api_url='http://localhost:3000',
            is_default=True,
            enable_anti_ban=True,
            max_messages_per_hour=100,
            max_messages_per_day=500
        )
        db.session.add(self.instance)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_spintax_resolution(self):
        """Verifica se o motor Spintax resolve alternativas corretamente."""
        template = "{Olá|Oi|Bom dia}, {tudo bem|como vai}?"
        for _ in range(10):
            resolved = resolve_spintax(template)
            self.assertFalse('{' in resolved)
            self.assertFalse('}' in resolved)
            self.assertFalse('|' in resolved)
            self.assertTrue(any(g in resolved for g in ['Olá', 'Oi', 'Bom dia']))
            self.assertTrue(any(s in resolved for s in ['tudo bem', 'como vai']))

    def test_variable_resolution(self):
        """Verifica se as variáveis ricas são preenchidas corretamente."""
        client = Client(name='Fabio Nunes', status='lead', segment='Tecnologia', address='Rua X - São Paulo')
        recipient = BulkCampaignRecipient(name='Fabio Nunes', phone='11999998888')

        template = "[SAUDACAO_HORARIO], [PRIMEIRO_NOME]! Seu status atual é [STATUS] na empresa de [EMPRESA]."
        resolved = resolve_message_variables(template, recipient, client)

        self.assertIn("Fabio", resolved)
        self.assertIn("Lead", resolved)
        self.assertIn("Tecnologia", resolved)
        greeting = get_time_greeting()
        self.assertIn(greeting, resolved)

    def test_master_switch_toggle(self):
        """Verifica se o Master Switch global do motor altera estado e desliga/liga."""
        set_master_switch(True)
        self.assertTrue(is_master_switch_enabled())

        set_master_switch(False)
        self.assertFalse(is_master_switch_enabled())

        set_master_switch(True)
        self.assertTrue(is_master_switch_enabled())

    def test_filter_query_and_anti_fatigue(self):
        """Verifica se os filtros de funil, DDD e anti-fadiga excluem leads contatados recentemente."""
        # 1. Lead recente (contatado hoje)
        c1 = Client(name='Lead Recente', phone='11999991111', status='lead')
        # 2. Lead frio (sem contato recente)
        c2 = Client(name='Lead Frio', phone='11988882222', status='lead')
        # 3. Lead de outro DDD (21)
        c3 = Client(name='Lead RJ', phone='21977773333', status='lead')
        # 4. Lead proposta
        c4 = Client(name='Cliente Proposta', phone='11966664444', status='proposta')

        db.session.add_all([c1, c2, c3, c4])
        db.session.commit()

        # Adiciona log de mensagem recente para c1
        log = MessageLog(client_id=c1.id, content='Msg de ontem', channel='whatsapp_waha', status='sent', timestamp=datetime.utcnow() - timedelta(hours=10))
        db.session.add(log)
        db.session.commit()

        # Filtro: Apenas leads com DDD 11 e regra anti-fadiga de 2 dias
        filters = {
            'statuses': ['lead'],
            'ddds': ['11'],
            'anti_fatigue_days': 2
        }
        query = build_client_filter_query(filters)
        results = query.all()

        # Apenas c2 deve ser qualificado (c1 é recente e c3 é DDD 21)
        result_phones = [r.phone for r in results]
        self.assertIn('11988882222', result_phones)
        self.assertNotIn('11999991111', result_phones)
        self.assertNotIn('21977773333', result_phones)

    def test_filter_multiple_segments_and_categories(self):
        """Verifica a seleção de múltiplos Segmentos e Categorias simultaneamente."""
        c_tec = Client(name='Cliente Tech', phone='11911110001', segment='Tecnologia', status='lead')
        c_sau = Client(name='Cliente Saúde', phone='11911110002', segment='Saúde', status='lead')
        c_var = Client(name='Cliente Varejo', phone='11911110003', category='Varejo', status='lead')
        c_ind = Client(name='Cliente Indústria', phone='11911110004', segment='Indústria', status='lead')

        db.session.add_all([c_tec, c_sau, c_var, c_ind])
        db.session.commit()

        # Filtro com lista de múltiplos segmentos/categorias: Tecnologia e Varejo
        filters = {
            'statuses': ['lead'],
            'segments': ['Tecnologia', 'Varejo']
        }
        query = build_client_filter_query(filters)
        results = query.all()
        result_phones = [r.phone for r in results]

        self.assertIn('11911110001', result_phones) # Tecnologia
        self.assertIn('11911110003', result_phones) # Varejo (está em category)
        self.assertNotIn('11911110002', result_phones) # Saúde (não selecionado)
        self.assertNotIn('11911110004', result_phones) # Indústria (não selecionado)

        # Teste com string separada por vírgula
        filters_csv = {
            'statuses': ['lead'],
            'segments': 'Saúde, Indústria'
        }
        query_csv = build_client_filter_query(filters_csv)
        results_csv = query_csv.all()
        result_phones_csv = [r.phone for r in results_csv]

        self.assertIn('11911110002', result_phones_csv) # Saúde
        self.assertIn('11911110004', result_phones_csv) # Indústria
        self.assertNotIn('11911110001', result_phones_csv)


    def test_campaign_creation_and_lifecycle(self):
        """Verifica a criação da campanha, compilação da fila com desduplicação e controle de pausa/cancelamento."""
        camp = BulkCampaign(
            name="Campanha Teste",
            status="draft",
            message_text="{Oi|Ola} [PRIMEIRO_NOME]",
            waha_instance_id=self.instance.id,
            created_by_id=self.user.id,
            total_count=2
        )
        db.session.add(camp)
        db.session.commit()

        r1 = BulkCampaignRecipient(campaign_id=camp.id, name="João", phone="11999990001", status="pending")
        r2 = BulkCampaignRecipient(campaign_id=camp.id, name="Maria", phone="11999990002", status="pending")
        db.session.add_all([r1, r2])
        db.session.commit()

        # Testa pausa
        ok, msg = pause_campaign_engine(camp.id, reason="Teste de pausa")
        self.assertTrue(ok)
        self.assertEqual(camp.status, 'paused')

        # Testa cancelamento
        ok_cancel, msg_cancel = cancel_campaign_engine(camp.id)
        self.assertTrue(ok_cancel)
        self.assertEqual(camp.status, 'cancelled')

        # Verifica se os recipients pendentes foram marcados como cancelled
        pending_count = BulkCampaignRecipient.query.filter_by(campaign_id=camp.id, status='pending').count()
        self.assertEqual(pending_count, 0)

    def test_graceful_shutdown_without_loss(self):
        """Verifica se o desligamento do módulo congela as campanhas sem prejuízo ou perda de dados."""
        from app.tasks.bulk_engine import freeze_engine_gracefully, is_bulk_module_enabled
        from app.core.module_registry import is_module_enabled

        # Cria campanha em execução
        camp = BulkCampaign(
            name="Campanha em Andamento",
            status="running",
            message_text="Olá [PRIMEIRO_NOME]",
            waha_instance_id=self.instance.id,
            created_by_id=self.user.id,
            total_count=3,
            processed_count=1,
            success_count=1
        )
        db.session.add(camp)
        db.session.commit()

        # Recipient já enviado e 2 pendentes
        r_sent = BulkCampaignRecipient(campaign_id=camp.id, name="Enviado", phone="11999990001", status="sent")
        r_pend1 = BulkCampaignRecipient(campaign_id=camp.id, name="Pendente 1", phone="11999990002", status="pending")
        r_pend2 = BulkCampaignRecipient(campaign_id=camp.id, name="Pendente 2", phone="11999990003", status="pending")
        db.session.add_all([r_sent, r_pend1, r_pend2])
        db.session.commit()

        # Desliga o módulo com segurança
        paused_count = freeze_engine_gracefully("Módulo desativado com segurança pelo operador")
        self.assertEqual(paused_count, 1)

        # Recarrega a campanha
        db.session.refresh(camp)
        self.assertEqual(camp.status, 'paused')
        self.assertIn("Módulo desativado", camp.pause_reason)

        # ZERO PREJUÍZO: Os contatos pendentes continuam intactos como 'pending' para serem retomados!
        pending_count = BulkCampaignRecipient.query.filter_by(campaign_id=camp.id, status='pending').count()
        self.assertEqual(pending_count, 2)
        sent_count = BulkCampaignRecipient.query.filter_by(campaign_id=camp.id, status='sent').count()
        self.assertEqual(sent_count, 1)


if __name__ == '__main__':
    unittest.main()
