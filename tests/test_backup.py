import os
import unittest
from config import TestConfig
from app import create_app, db
from app.models import User, Client, Setting
from app.utils.backup_manager import BackupManager

class TestBackupManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(TestConfig)
        cls.client = cls.app.test_client()
        with cls.app.app_context():
            db.create_all()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    def test_backup_create_list_and_restore(self):
        # 1. Cria dados de teste
        client = Client(name="Cliente Backup Teste", phone="5511999990000", email="backup@teste.com")
        db.session.add(client)
        setting = Setting(key="teste_backup_key", value="12345")
        db.session.add(setting)
        db.session.commit()
        client_id = client.id

        # 2. Cria o backup
        result = BackupManager.create_backup()
        self.assertTrue(result.get('success'))
        filename = result.get('filename')
        file_path = result.get('file_path')
        self.assertTrue(os.path.exists(file_path))

        # 3. Lista backups
        backups = BackupManager.list_backups()
        self.assertTrue(any(b['filename'] == filename for b in backups))

        # 4. Modifica os dados no banco
        client_to_mod = Client.query.get(client_id)
        client_to_mod.name = "Nome Alterado"
        db.session.commit()
        self.assertEqual(Client.query.get(client_id).name, "Nome Alterado")

        # 5. Restaura o backup
        restore_result = BackupManager.restore_backup(file_path)
        self.assertTrue(restore_result.get('success'))

        # 6. Verifica que o dado original foi restaurado
        restored_client = Client.query.get(client_id)
        self.assertEqual(restored_client.name, "Cliente Backup Teste")

        # 7. Exclui o arquivo temporário de backup
        deleted = BackupManager.delete_backup(filename)
        self.assertTrue(deleted)
        self.assertFalse(os.path.exists(file_path))
