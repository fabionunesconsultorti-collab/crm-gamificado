import os
import json
import gzip
import unittest
from config import TestConfig
from app import create_app, db
from app.models import User, Client, Setting, KnowledgeDoc
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
        # 1. Cria dados de teste relacionais e de IA (RAG)
        client = Client(name="Cliente Backup Teste", phone="5511999990000", email="backup@teste.com")
        db.session.add(client)
        setting = Setting(key="teste_backup_key", value="12345")
        db.session.add(setting)
        
        doc = KnowledgeDoc(
            title="FAQ Teste de Backup",
            category="faq",
            doc_type="faq",
            content="Pergunta: Como funciona o backup? Resposta: Salva banco, RAG e configs.",
            chunks_count=1,
            is_active=True
        )
        db.session.add(doc)
        db.session.commit()
        
        client_id = client.id
        doc_id = doc.id

        # 2. Cria o backup completo
        result = BackupManager.create_backup()
        self.assertTrue(result.get('success'))
        self.assertTrue(result.get('rag_included'))
        self.assertGreaterEqual(result.get('rag_docs_count', 0), 1)

        filename = result.get('filename')
        file_path = result.get('file_path')
        self.assertTrue(os.path.exists(file_path))

        # 3. Lista backups e verifica metadados detalhados
        backups = BackupManager.list_backups()
        target_backup = next((b for b in backups if b['filename'] == filename), None)
        self.assertIsNotNone(target_backup)
        self.assertTrue(target_backup.get('has_rag'))
        self.assertGreaterEqual(target_backup.get('rag_docs_count', 0), 1)

        # 4. Modifica os dados no banco
        client_to_mod = Client.query.get(client_id)
        client_to_mod.name = "Nome Alterado"
        doc_to_mod = KnowledgeDoc.query.get(doc_id)
        doc_to_mod.title = "Título Modificado"
        db.session.commit()
        
        self.assertEqual(Client.query.get(client_id).name, "Nome Alterado")
        self.assertEqual(KnowledgeDoc.query.get(doc_id).title, "Título Modificado")

        # 5. Restaura o backup
        restore_result = BackupManager.restore_backup(file_path)
        self.assertTrue(restore_result.get('success'))
        self.assertIn('knowledge_docs', restore_result.get('stats', {}))

        # 6. Verifica que ambos os dados foram restaurados fielmente
        restored_client = Client.query.get(client_id)
        self.assertEqual(restored_client.name, "Cliente Backup Teste")

        restored_doc = KnowledgeDoc.query.get(doc_id)
        self.assertEqual(restored_doc.title, "FAQ Teste de Backup")
        self.assertIn("Pergunta: Como funciona o backup?", restored_doc.content)

        # 7. Exclui o arquivo temporário de backup
        deleted = BackupManager.delete_backup(filename)
        self.assertTrue(deleted)
        self.assertFalse(os.path.exists(file_path))

    def test_legacy_backup_compatibility(self):
        """Garante que backups no formato antigo (sem RAG ou uploads) ainda são restaurados com 100% de sucesso."""
        legacy_payload = {
            "metadata": {
                "version": "CRM_PRO_1.0",
                "counts": {"settings": 1}
            },
            "data": {
                "settings": [{"id": 9999, "key": "legacy_key", "value": "legacy_val"}]
            }
        }
        json_bytes = json.dumps(legacy_payload).encode('utf-8')
        compressed = gzip.compress(json_bytes)
        
        backup_dir = BackupManager.get_backup_dir()
        legacy_fn = "backup_legacy_test.json.gz"
        legacy_path = os.path.join(backup_dir, legacy_fn)
        with open(legacy_path, 'wb') as f:
            f.write(compressed)

        try:
            restore_result = BackupManager.restore_backup(legacy_path)
            self.assertTrue(restore_result.get('success'))
            
            s = Setting.query.filter_by(key="legacy_key").first()
            self.assertIsNotNone(s)
            self.assertEqual(s.value, "legacy_val")
        finally:
            if os.path.exists(legacy_path):
                os.remove(legacy_path)
            s_del = Setting.query.filter_by(key="legacy_key").first()
            if s_del:
                db.session.delete(s_del)
                db.session.commit()
