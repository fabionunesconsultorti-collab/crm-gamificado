import os
import io
import json
import gzip
import logging
import tarfile
import base64
import hashlib
from datetime import datetime, date
from flask import current_app
from sqlalchemy import text
from app import db
from app.models import (
    User, Client, MessageLog, Setting, Store,
    MessageTemplate, WahaInstance, ScrapingJob,
    FileMappingTemplate, SystemLog, KnowledgeDoc
)

logger = logging.getLogger(__name__)

# Modelos em ordem de dependência para inserção / restauração segura
ORDERED_MODELS = [
    ('users', User),
    ('stores', Store),
    ('waha_instances', WahaInstance),
    ('settings', Setting),
    ('message_templates', MessageTemplate),
    ('file_mapping_templates', FileMappingTemplate),
    ('clients', Client),
    ('knowledge_docs', KnowledgeDoc),
    ('scraping_jobs', ScrapingJob),
    ('message_logs', MessageLog),
    ('system_logs', SystemLog),
]


def _json_serial(obj):
    """Serializador para objetos JSON não nativos como datetime e date."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def _parse_datetime(val):
    """Converte string ISO para datetime se aplicável."""
    if not val or not isinstance(val, str):
        return val
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return val


class BackupManager:
    @staticmethod
    def get_backup_dir():
        backup_dir = current_app.config.get('BACKUP_DIR') or os.path.join(current_app.root_path, '..', 'backups')
        backup_dir = os.path.abspath(backup_dir)
        os.makedirs(backup_dir, exist_ok=True)
        return backup_dir

    @staticmethod
    def get_chroma_dir():
        """Retorna o diretório persistente do ChromaDB com prioridade para o caminho do workspace."""
        p1 = os.path.abspath(os.path.join(current_app.root_path, '..', 'chroma_data'))
        if os.path.exists(p1):
            return p1
        p2 = os.path.abspath(os.path.join(os.getcwd(), 'chroma_data'))
        return p2

    @staticmethod
    def get_uploads_dir():
        """Retorna o diretório de uploads estáticos do CRM."""
        uploads = os.path.abspath(os.path.join(current_app.root_path, 'static', 'uploads'))
        os.makedirs(uploads, exist_ok=True)
        return uploads

    @staticmethod
    def get_env_file_path():
        """Retorna o caminho do arquivo de variáveis de ambiente .env."""
        return os.path.abspath(os.path.join(current_app.root_path, '..', '.env'))

    @classmethod
    def _archive_directory_to_b64(cls, dir_path):
        """Compacta um diretório em tar.gz na memória e retorna codificado em base64 com checksum SHA256."""
        if not os.path.exists(dir_path) or not os.path.isdir(dir_path):
            return None

        file_count = 0
        total_size = 0
        buf = io.BytesIO()

        try:
            with tarfile.open(mode="w:gz", fileobj=buf) as tar:
                for root, _, files in os.walk(dir_path):
                    for file in files:
                        if file.endswith(('.tmp', '.sock', '.lock')):
                            continue
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, dir_path)
                        try:
                            tar.add(full_path, arcname=rel_path)
                            file_count += 1
                            total_size += os.path.getsize(full_path)
                        except Exception as e:
                            logger.warning(f"[Backup] Aviso ao arquivar {full_path}: {e}")

            if file_count == 0:
                return None

            compressed_bytes = buf.getvalue()
            sha256 = hashlib.sha256(compressed_bytes).hexdigest()
            b64_str = base64.b64encode(compressed_bytes).decode('ascii')

            return {
                "data_b64": b64_str,
                "file_count": file_count,
                "raw_size": total_size,
                "compressed_size": len(compressed_bytes),
                "sha256": sha256
            }
        except Exception as e:
            logger.error(f"[Backup] Erro ao compactar diretório {dir_path}: {e}", exc_info=True)
            return None

    @classmethod
    def _restore_directory_from_b64(cls, archive_dict, target_dir):
        """Extrai um arquivo tar.gz codificado em base64 para o diretório de destino com validação de segurança."""
        if not archive_dict or not archive_dict.get('data_b64'):
            return {"success": False, "error": "Arquivo vazio ou inválido."}

        try:
            compressed_bytes = base64.b64decode(archive_dict['data_b64'])
            expected_sha = archive_dict.get('sha256')
            if expected_sha and hashlib.sha256(compressed_bytes).hexdigest() != expected_sha:
                return {"success": False, "error": "Checksum SHA256 corrompido ou inválido."}

            os.makedirs(target_dir, exist_ok=True)
            buf = io.BytesIO(compressed_bytes)

            files_restored = 0
            with tarfile.open(mode="r:gz", fileobj=buf) as tar:
                for member in tar.getmembers():
                    # Proteção contra Directory Traversal (Tar Slip)
                    target_path = os.path.abspath(os.path.join(target_dir, member.name))
                    if not target_path.startswith(os.path.abspath(target_dir)):
                        logger.warning(f"[Backup Security] Caminho inseguro ignorado na restauração: {member.name}")
                        continue
                    if member.isdir():
                        os.makedirs(target_path, exist_ok=True)
                    else:
                        if hasattr(tarfile, 'data_filter'):
                            tar.extract(member, path=target_dir, filter='data')
                        else:
                            tar.extract(member, path=target_dir)
                        files_restored += 1

            return {"success": True, "files_restored": files_restored}
        except Exception as e:
            logger.error(f"[Backup Restore] Erro ao descompactar em {target_dir}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    @classmethod
    def create_backup(cls, destination="local", upload_gdrive=False):
        """
        Gera um backup completo e estruturado de todo o ecossistema CRM Pro:
        1. 11 Tabelas do Banco de Dados (incluindo KnowledgeDoc da IA).
        2. Base Vetorial Física do RAG (ChromaDB com todos os embeddings e índices).
        3. Arquivos de Mídia e Customização Visual (Logotipos e Uploads estáticos).
        4. Snapshot de Configurações de Ambiente (.env e variáveis operacionais).
        Salva em formato JSON compactado com gzip (.json.gz).
        """
        timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"backup_crm_{timestamp_str}.json.gz"
        backup_dir = cls.get_backup_dir()
        file_path = os.path.join(backup_dir, filename)

        tables_data = {}
        counts = {}

        try:
            # 1. Extração dos registros relacionais
            for key, model in ORDERED_MODELS:
                records = model.query.all()
                rows = []
                for rec in records:
                    row_dict = {}
                    for col in rec.__table__.columns:
                        val = getattr(rec, col.name)
                        if isinstance(val, (datetime, date)):
                            row_dict[col.name] = val.isoformat()
                        else:
                            row_dict[col.name] = val
                    rows.append(row_dict)
                tables_data[key] = rows
                counts[key] = len(rows)

            # 2. Base Vetorial do RAG (ChromaDB)
            chroma_dir = cls.get_chroma_dir()
            rag_archive = cls._archive_directory_to_b64(chroma_dir)

            # 3. Mídias e Branding (Uploads)
            uploads_dir = cls.get_uploads_dir()
            uploads_archive = cls._archive_directory_to_b64(uploads_dir)

            # 4. Arquivo de ambiente (.env) e Variáveis Operacionais
            env_path = cls.get_env_file_path()
            env_content = None
            if os.path.exists(env_path) and os.path.isfile(env_path):
                try:
                    with open(env_path, 'r', encoding='utf-8', errors='ignore') as ef:
                        env_content = ef.read()
                except Exception as ef_err:
                    logger.warning(f"[Backup] Aviso ao ler .env: {ef_err}")

            key_env_vars = {}
            for var in ['DATABASE_URL', 'REDIS_URL', 'MAPS_SCRAPER_URL', 'BACKUP_DIR', 'USE_SQLITE',
                        'POSTGRES_USER', 'POSTGRES_HOST', 'POSTGRES_PORT', 'POSTGRES_DB', 'OLLAMA_URL']:
                val = os.environ.get(var)
                if val:
                    if 'password' in var.lower() or 'secret' in var.lower():
                        key_env_vars[var] = '********'
                    else:
                        key_env_vars[var] = val

            backup_payload = {
                "metadata": {
                    "version": "CRM_PRO_3.0_FULL",
                    "created_at": datetime.now().isoformat(),
                    "filename": filename,
                    "counts": counts,
                    "total_records": sum(counts.values()),
                    "database_type": db.engine.dialect.name,
                    "rag": {
                        "included": True,
                        "docs_count": counts.get('knowledge_docs', 0),
                        "vector_store_included": rag_archive is not None,
                        "vector_files_count": rag_archive.get('file_count', 0) if rag_archive else 0,
                        "vector_raw_size": rag_archive.get('raw_size', 0) if rag_archive else 0
                    },
                    "uploads": {
                        "included": uploads_archive is not None,
                        "files_count": uploads_archive.get('file_count', 0) if uploads_archive else 0,
                        "total_size": uploads_archive.get('raw_size', 0) if uploads_archive else 0
                    },
                    "system_config": {
                        "env_file_included": env_content is not None,
                        "settings_count": counts.get('settings', 0)
                    }
                },
                "data": tables_data,
                "rag_vector_store": rag_archive,
                "uploads_store": uploads_archive,
                "system_config": {
                    "env_content": env_content,
                    "env_vars": key_env_vars
                }
            }

            # Serializa e compacta com GZIP
            json_bytes = json.dumps(backup_payload, ensure_ascii=False, default=_json_serial).encode('utf-8')
            with gzip.open(file_path, 'wb') as f:
                f.write(json_bytes)

            file_size = os.path.getsize(file_path)
            logger.info(
                f"[Backup] Backup completo gerado com sucesso: {filename} "
                f"({file_size} bytes, {sum(counts.values())} registros, "
                f"RAG: {counts.get('knowledge_docs', 0)} docs + {'vetores' if rag_archive else 'sem vetores'}, "
                f"Uploads: {uploads_archive.get('file_count', 0) if uploads_archive else 0} arquivos)"
            )

            # Atualiza no Setting a data do último backup
            Setting.set('backup_last_run', datetime.now().strftime("%d/%m/%Y %H:%M:%S"))

            # Sincronização opcional com Google Drive
            gdrive_status = None
            if upload_gdrive or Setting.get('gdrive_enabled', 'false').lower() in ('true', '1'):
                success_gd, msg_gd = cls.upload_to_gdrive(file_path)
                gdrive_status = {"success": success_gd, "message": msg_gd}
                Setting.set('gdrive_last_status', f"{'✔ Sucesso' if success_gd else '❌ Erro'}: {msg_gd} ({datetime.now().strftime('%d/%m/%Y %H:%M')})")

            # Aplica rotação e limpeza de backups locais antigos
            cls.enforce_retention_policy()

            return {
                "success": True,
                "filename": filename,
                "file_path": file_path,
                "size_bytes": file_size,
                "total_records": sum(counts.values()),
                "counts": counts,
                "rag_included": True,
                "rag_docs_count": counts.get('knowledge_docs', 0),
                "rag_vector_included": rag_archive is not None,
                "uploads_included": uploads_archive is not None,
                "uploads_count": uploads_archive.get('file_count', 0) if uploads_archive else 0,
                "gdrive": gdrive_status
            }

        except Exception as e:
            logger.error(f"[Backup] Falha ao criar backup completo: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    @classmethod
    def restore_backup(cls, file_stream_or_path, restore_rag=True, restore_uploads=True, restore_env=True):
        """
        Restaura o sistema integralmente a partir de um arquivo .json.gz ou .json:
        1. Restaura todas as tabelas dentro de uma transação atômica protegida com rollback.
        2. Restaura o banco vetorial do ChromaDB e reinicializa a conexão do RAGEngine.
        3. Restaura os arquivos de mídia estáticos (logos e uploads).
        4. Restaura/preserva as configurações de ambiente (.env).
        Compatível tanto com backups legados (somente banco) quanto com novos backups completos.
        """
        try:
            # 1. Carrega os dados brutos
            if isinstance(file_stream_or_path, str):
                if file_stream_or_path.endswith('.gz'):
                    with gzip.open(file_stream_or_path, 'rb') as f:
                        raw_data = f.read().decode('utf-8')
                else:
                    with open(file_stream_or_path, 'r', encoding='utf-8') as f:
                        raw_data = f.read()
            else:
                content = file_stream_or_path.read()
                try:
                    raw_data = gzip.decompress(content).decode('utf-8')
                except Exception:
                    raw_data = content.decode('utf-8')

            payload = json.loads(raw_data)
            if "metadata" not in payload or "data" not in payload:
                return {"success": False, "error": "Formato de backup inválido (metadados ausentes)."}

            data = payload["data"]
            stats = {}

            # 2. Executa a restauração relacional dentro de transação segura
            for key, model in ORDERED_MODELS:
                rows = data.get(key, [])
                restored_count = 0
                for row_dict in rows:
                    rec_id = row_dict.get('id')
                    existing = model.query.get(rec_id) if rec_id else None

                    processed_dict = {}
                    for k, v in row_dict.items():
                        col = model.__table__.columns.get(k)
                        if col is not None and str(col.type).lower().startswith(('date', 'timestamp')):
                            processed_dict[k] = _parse_datetime(v)
                        else:
                            processed_dict[k] = v

                    if existing:
                        for k, v in processed_dict.items():
                            setattr(existing, k, v)
                    else:
                        new_inst = model(**processed_dict)
                        db.session.add(new_inst)

                    restored_count += 1
                stats[key] = restored_count

            db.session.commit()

            # Ajusta sequences de auto-incremento do PostgreSQL
            if db.engine.dialect.name == 'postgresql':
                for key, model in ORDERED_MODELS:
                    tbl_name = model.__table__.name
                    try:
                        db.session.execute(text(f"""
                            SELECT setval(
                                pg_get_serial_sequence('"{tbl_name}"', 'id'),
                                COALESCE((SELECT MAX(id) FROM "{tbl_name}"), 1),
                                true
                            );
                        """))
                        db.session.commit()
                    except Exception as seq_err:
                        db.session.rollback()
                        logger.debug(f"[Backup Restore] Sequence para {tbl_name} não requer ajuste: {seq_err}")

            # 3. Restauração da Base Vetorial RAG (ChromaDB)
            rag_restored = False
            rag_vector_files = 0
            if restore_rag and "rag_vector_store" in payload and payload["rag_vector_store"]:
                chroma_dir = cls.get_chroma_dir()
                # Libera conexão atual do ChromaDB antes de restaurar arquivos
                try:
                    from app.utils.rag_engine import RAGEngine
                    if hasattr(RAGEngine, '_chroma_client') and RAGEngine._chroma_client is not None:
                        if hasattr(RAGEngine._chroma_client, 'close'):
                            RAGEngine._chroma_client.close()
                    RAGEngine._collection = None
                    RAGEngine._chroma_client = None
                except Exception:
                    pass

                rag_res = cls._restore_directory_from_b64(payload["rag_vector_store"], chroma_dir)
                if rag_res.get('success'):
                    rag_restored = True
                    rag_vector_files = rag_res.get('files_restored', 0)
                    logger.info(f"[Backup Restore] Base vetorial RAG extraída com sucesso ({rag_vector_files} arquivos).")
                    # Reinicializa o singleton do ChromaDB
                    try:
                        from app.utils.rag_engine import RAGEngine
                        RAGEngine.reload_collection()
                    except Exception as rag_reload_err:
                        logger.warning(f"[Backup Restore] Aviso ao recarregar RAGEngine: {rag_reload_err}")
                else:
                    logger.warning(f"[Backup Restore] Falha ao extrair base vetorial: {rag_res.get('error')}")

            # 4. Fallback / Sincronização inteligente do RAG caso os vetores não estivessem no backup
            if restore_rag and not rag_restored and stats.get('knowledge_docs', 0) > 0:
                try:
                    from app.utils.rag_engine import RAGEngine
                    col = RAGEngine.get_collection()
                    if col is not None and col.count() == 0:
                        active_docs = KnowledgeDoc.query.filter_by(is_active=True).all()
                        if active_docs:
                            logger.info(f"[Backup Restore] Auto-sincronizando {len(active_docs)} documentos restaurados no ChromaDB...")
                            for doc in active_docs:
                                RAGEngine.index_document(doc.id, doc.title, doc.content, doc.category)
                            rag_restored = True
                except Exception as auto_rag_err:
                    logger.warning(f"[Backup Restore] Aviso no auto-reindex do RAG: {auto_rag_err}")

            # 5. Restauração de Mídias e Uploads (Logos)
            uploads_restored = False
            uploads_count = 0
            if restore_uploads and "uploads_store" in payload and payload["uploads_store"]:
                uploads_dir = cls.get_uploads_dir()
                up_res = cls._restore_directory_from_b64(payload["uploads_store"], uploads_dir)
                if up_res.get('success'):
                    uploads_restored = True
                    uploads_count = up_res.get('files_restored', 0)
                    logger.info(f"[Backup Restore] Arquivos de mídia/uploads restaurados ({uploads_count} arquivos).")

            # 6. Preservação / Restauração de Configuração de Ambiente (.env)
            env_restored = False
            if restore_env and "system_config" in payload and payload["system_config"]:
                env_content = payload["system_config"].get("env_content")
                if env_content:
                    env_path = cls.get_env_file_path()
                    try:
                        if not os.path.exists(env_path):
                            with open(env_path, 'w', encoding='utf-8') as ef:
                                ef.write(env_content)
                            env_restored = True
                            logger.info("[Backup Restore] Arquivo .env restaurado na raiz.")
                        else:
                            backup_env_path = env_path + '.backup_restored'
                            with open(backup_env_path, 'w', encoding='utf-8') as ef:
                                ef.write(env_content)
                            env_restored = True
                            logger.info("[Backup Restore] Snapshot de ambiente salvo como .env.backup_restored.")
                    except Exception as env_err:
                        logger.warning(f"[Backup Restore] Erro ao salvar arquivo .env: {env_err}")

            return {
                "success": True,
                "message": "Backup completo restaurado com sucesso!",
                "stats": stats,
                "total_records": sum(stats.values()),
                "rag_restored": rag_restored,
                "rag_docs_count": stats.get('knowledge_docs', 0),
                "rag_vector_files": rag_vector_files,
                "uploads_restored": uploads_restored,
                "uploads_count": uploads_count,
                "env_restored": env_restored,
                "metadata": payload.get("metadata", {})
            }

        except Exception as e:
            db.session.rollback()
            logger.error(f"[Backup Restore] Erro fatal na restauração: {e}", exc_info=True)
            return {"success": False, "error": f"Falha na restauração: {str(e)}"}

    @classmethod
    def list_backups(cls):
        """Lista todos os arquivos de backup salvos localmente com metadados expandidos."""
        backup_dir = cls.get_backup_dir()
        backups = []
        if not os.path.exists(backup_dir):
            return backups

        for fn in sorted(os.listdir(backup_dir), reverse=True):
            if fn.endswith(('.json.gz', '.json', '.sql')):
                fp = os.path.join(backup_dir, fn)
                st = os.stat(fp)
                size_kb = round(st.st_size / 1024, 1)
                size_mb = round(st.st_size / (1024 * 1024), 2)
                size_display = f"{size_mb} MB" if size_mb >= 1.0 else f"{size_kb} KB"
                mod_time = datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M:%S")

                total_records = None
                has_rag = False
                rag_docs_count = 0
                has_uploads = False
                version = "Legado"

                if (fn.endswith('.json.gz') or fn.endswith('.json')) and st.st_size < 10 * 1024 * 1024:
                    try:
                        if fn.endswith('.gz'):
                            with gzip.open(fp, 'rb') as f:
                                payload = json.loads(f.read().decode('utf-8'))
                        else:
                            with open(fp, 'r', encoding='utf-8') as f:
                                payload = json.load(f)

                        meta = payload.get('metadata', {})
                        version = meta.get('version', 'CRM_PRO_2.0')
                        total_records = meta.get('total_records', sum(meta.get('counts', {}).values()))
                        rag_meta = meta.get('rag', {})
                        has_rag = bool(
                            rag_meta.get('vector_store_included') or
                            meta.get('counts', {}).get('knowledge_docs', 0) > 0 or
                            'rag_vector_store' in payload
                        )
                        rag_docs_count = rag_meta.get('docs_count', meta.get('counts', {}).get('knowledge_docs', 0))
                        has_uploads = bool(
                            meta.get('uploads', {}).get('included') or
                            'uploads_store' in payload
                        )
                    except Exception as meta_err:
                        logger.debug(f"[Backup] Não foi possível ler metadados detalhados de {fn}: {meta_err}")

                backups.append({
                    "filename": fn,
                    "path": fp,
                    "size_display": size_display,
                    "size_bytes": st.st_size,
                    "created_at": mod_time,
                    "total_records": total_records,
                    "has_rag": has_rag,
                    "rag_docs_count": rag_docs_count,
                    "has_uploads": has_uploads,
                    "version": version
                })
        return backups

    @classmethod
    def delete_backup(cls, filename):
        """Exclui um arquivo de backup local com validação de segurança."""
        backup_dir = cls.get_backup_dir()
        safe_fn = os.path.basename(filename)
        fp = os.path.join(backup_dir, safe_fn)
        if os.path.exists(fp) and os.path.isfile(fp):
            os.remove(fp)
            return True
        return False

    @classmethod
    def enforce_retention_policy(cls):
        """Remove backups locais que excedam a política de retenção configurada."""
        try:
            retention_days = int(Setting.get('backup_retention_days', '7'))
        except (ValueError, TypeError):
            retention_days = 7

        backup_dir = cls.get_backup_dir()
        now = datetime.now()
        for fn in os.listdir(backup_dir):
            if fn.endswith(('.json.gz', '.json', '.sql')):
                fp = os.path.join(backup_dir, fn)
                st = os.stat(fp)
                age_days = (now - datetime.fromtimestamp(st.st_mtime)).days
                if age_days > retention_days:
                    try:
                        os.remove(fp)
                        logger.info(f"[Backup Retention] Removido backup expirado ({age_days} dias): {fn}")
                    except Exception as e:
                        logger.warning(f"[Backup Retention] Erro ao remover {fn}: {e}")

    @classmethod
    def upload_to_gdrive(cls, file_path):
        """
        Faz upload do arquivo de backup para o Google Drive utilizando
        as credenciais de Service Account configuradas no CRM.
        """
        folder_id = Setting.get('gdrive_folder_id', '').strip()
        creds_json = Setting.get('gdrive_credentials_json', '').strip()

        if not creds_json:
            return False, "Credenciais do Google Drive não configuradas (JSON de Service Account vazio)."

        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload

            creds_dict = json.loads(creds_json)
            scopes = ['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/drive']
            credentials = service_account.Credentials.from_service_account_info(creds_dict, scopes=scopes)
            drive_service = build('drive', 'v3', credentials=credentials)

            filename = os.path.basename(file_path)
            file_metadata = {'name': filename}
            if folder_id:
                file_metadata['parents'] = [folder_id]

            media = MediaFileUpload(file_path, mimetype='application/gzip', resumable=True)
            uploaded_file = drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, webViewLink'
            ).execute()

            logger.info(f"[Google Drive] Upload concluído: {filename} (ID: {uploaded_file.get('id')})")
            return True, f"Upload concluído no Google Drive! Arquivo: {uploaded_file.get('name')} (ID: {uploaded_file.get('id')})"

        except json.JSONDecodeError:
            return False, "O JSON das credenciais do Google Drive é inválido ou está mal formatado."
        except Exception as e:
            logger.error(f"[Google Drive] Erro no upload: {e}", exc_info=True)
            return False, f"Erro na API do Google Drive: {str(e)}"

    @classmethod
    def test_gdrive_connection(cls, folder_id, creds_json):
        """Testa se as credenciais fornecidas conseguem se autenticar e acessar a pasta no Google Drive."""
        if not creds_json:
            return False, "Por favor, insira o conteúdo JSON da chave da conta de serviço (Service Account)."

        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            creds_dict = json.loads(creds_json)
            scopes = ['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/drive']
            credentials = service_account.Credentials.from_service_account_info(creds_dict, scopes=scopes)
            drive_service = build('drive', 'v3', credentials=credentials)

            about = drive_service.about().get(fields="user").execute()
            user_email = about.get('user', {}).get('emailAddress', creds_dict.get('client_email', 'Service Account'))

            folder_name = "Raiz do Drive"
            if folder_id:
                folder_meta = drive_service.files().get(fileId=folder_id, fields="id, name, mimeType").execute()
                folder_name = folder_meta.get('name', folder_id)

            return True, f"Conexão com Google Drive bem-sucedida! Autenticado como: {user_email}. Pasta alvo: '{folder_name}'."

        except json.JSONDecodeError:
            return False, "O texto fornecido não é um JSON válido. Cole o arquivo JSON completo gerado no Google Cloud Console."
        except Exception as e:
            return False, f"Falha na autenticação do Google Drive: {str(e)}"
