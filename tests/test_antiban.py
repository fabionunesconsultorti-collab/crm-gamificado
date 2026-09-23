import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from app import create_app, db
from app.models import WahaInstance, User

class TestAntiBanSystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = cls.app.test_client()
        with cls.app.app_context():
            db.create_all()

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.drop_all()

    def setUp(self):
        with self.app.app_context():
            db.session.query(WahaInstance).delete()
            db.session.query(User).delete()
            admin = User(username="admin_test", email="admin@test.com", role="admin")
            admin.set_password("admin123")
            db.session.add(admin)
            db.session.commit()

    def test_warmup_daily_limits(self):
        with self.app.app_context():
            inst = WahaInstance(
                name="Warmup Instance",
                api_url="http://localhost:3000",
                session_name="test_warmup",
                enable_anti_ban=True,
                warmup_mode=True,
                max_messages_per_day=500
            )
            # Dia 1
            inst.warmup_start_date = datetime.utcnow()
            self.assertEqual(inst.get_effective_daily_limit(), 20)

            # Dia 2
            inst.warmup_start_date = datetime.utcnow() - timedelta(days=1)
            self.assertEqual(inst.get_effective_daily_limit(), 40)

            # Dia 3
            inst.warmup_start_date = datetime.utcnow() - timedelta(days=2)
            self.assertEqual(inst.get_effective_daily_limit(), 70)

            # Dia 7
            inst.warmup_start_date = datetime.utcnow() - timedelta(days=6)
            self.assertEqual(inst.get_effective_daily_limit(), 300)

            # Dia 15 (após curva base)
            inst.warmup_start_date = datetime.utcnow() - timedelta(days=14)
            self.assertEqual(inst.get_effective_daily_limit(), 500)

    def test_quiet_hours_detection(self):
        with self.app.app_context():
            inst = WahaInstance(
                name="Quiet Instance",
                api_url="http://localhost:3000",
                session_name="test_quiet",
                enable_anti_ban=True,
                quiet_hours_enabled=True,
                quiet_hours_start="22:00",
                quiet_hours_end="08:00"
            )

            # Às 23:30 (dentro do horário de silêncio)
            self.assertTrue(inst.is_in_quiet_hours(current_time_str="23:30"))
            # Às 03:00 (madrugada)
            self.assertTrue(inst.is_in_quiet_hours(current_time_str="03:00"))
            # Às 07:59 (dentro)
            self.assertTrue(inst.is_in_quiet_hours(current_time_str="07:59"))
            # Às 08:00 (fim do silêncio)
            self.assertFalse(inst.is_in_quiet_hours(current_time_str="08:00"))
            # Às 14:00 (fora do silêncio)
            self.assertFalse(inst.is_in_quiet_hours(current_time_str="14:00"))

    def test_hourly_and_daily_counter_resets(self):
        with self.app.app_context():
            inst = WahaInstance(
                name="Reset Instance",
                api_url="http://localhost:3000",
                session_name="test_resets",
                enable_anti_ban=True,
                max_messages_per_hour=80,
                max_messages_per_day=500,
                hourly_count=45,
                daily_count=120,
                last_sent_at=datetime(2026, 9, 20, 10, 30)
            )
            db.session.add(inst)
            db.session.commit()

            # Chamando reset para hora seguinte do mesmo dia
            inst.reset_counters_if_needed(current_dt=datetime(2026, 9, 20, 11, 15))
            self.assertEqual(inst.hourly_count, 0)
            self.assertEqual(inst.daily_count, 120)

            # Chamando reset para o dia seguinte
            inst.reset_counters_if_needed(current_dt=datetime(2026, 9, 21, 9, 0))
            self.assertEqual(inst.hourly_count, 0)
            self.assertEqual(inst.daily_count, 0)

    def test_check_anti_ban_limits_blocks_when_hourly_exceeded(self):
        with self.app.app_context():
            inst = WahaInstance(
                name="Hourly Block",
                api_url="http://localhost:3000",
                session_name="test_hourly_block",
                enable_anti_ban=True,
                max_messages_per_hour=10,
                hourly_count=10,
                last_sent_at=datetime.utcnow()
            )
            db.session.add(inst)
            db.session.commit()

            allowed, reason, stats = inst.check_anti_ban_limits(ignore_quiet_hours=True)
            self.assertFalse(allowed)
            self.assertEqual(stats['reason_code'], "hourly_limit")

    def test_record_message_sent_increments_counters(self):
        with self.app.app_context():
            inst = WahaInstance(
                name="Record Instance",
                api_url="http://localhost:3000",
                session_name="test_record",
                enable_anti_ban=True,
                max_messages_per_hour=80,
                max_messages_per_day=500,
                hourly_count=0,
                daily_count=0
            )
            db.session.add(inst)
            db.session.commit()

            inst.record_message_sent()
            db.session.commit()

            self.assertEqual(inst.hourly_count, 1)
            self.assertEqual(inst.daily_count, 1)
            self.assertIsNotNone(inst.last_sent_at)

    def test_api_anti_ban_stats_and_reset_endpoints(self):
        with self.app.app_context():
            inst = WahaInstance(
                name="API Instance",
                api_url="http://localhost:3000",
                session_name="api_test_inst",
                enable_anti_ban=True,
                min_delay_seconds=3,
                max_delay_seconds=8,
                max_messages_per_hour=50,
                max_messages_per_day=200,
                hourly_count=12,
                daily_count=45
            )
            db.session.add(inst)
            db.session.commit()
            inst_id = inst.id

        # Login como admin
        self.client.post('/auth/login', data={
            'username': 'admin_test',
            'password': 'admin123'
        }, follow_redirects=True)

        # GET stats
        response = self.client.get(f'/crm/api/waha/{inst_id}/anti_ban_stats')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['stats']['min_delay_seconds'], 3)
        self.assertEqual(data['stats']['max_delay_seconds'], 8)
        self.assertEqual(data['stats']['max_messages_per_hour'], 50)
        self.assertEqual(data['stats']['hourly_count'], 12)
        self.assertEqual(data['stats']['daily_count'], 45)

        # POST reset counters
        reset_res = self.client.post(f'/crm/api/waha/{inst_id}/reset_counters')
        self.assertEqual(reset_res.status_code, 200)
        reset_data = reset_res.get_json()
        self.assertTrue(reset_data['ok'])
        self.assertEqual(reset_data['stats']['hourly_count'], 0)
        self.assertEqual(reset_data['stats']['daily_count'], 0)
