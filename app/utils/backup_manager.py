import os
import io
import json
import gzip
import logging
from datetime import datetime, date
from flask import current_app
from sqlalchemy import text
from app import db
from app.models import (
    User, Client, MessageLog, Setting, Store,
    MessageTemplate, WahaInstance, ScrapingJob,
    FileMappingTemplate, SystemLog
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

    @classmethod
    def create_backup(cls, destination="local", upload_gdrive=False):
        """
        Gera um backup completo e estruturado de todas as tabelas do CRM Pro.
        Salva em formato JSON compactado com gzip (.json.gz).
        """
        timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"backup_crm_{timestamp_str}.json.gz"
        backup_dir = cls.get_backup_dir()
        file_path = os.path.join(backup_dir, filename)

        tables_data = {}
        counts = {}

        try:
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

            backup_payload = {
                "metadata": {
                    "version": "CRM_PRO_2.0",
                    "created_at": datetime.now().isoformat(),
                    "filename": filename,
                    "counts": counts,
                    "total_records": sum(counts.values()),
                    "database_type": db.engine.dialect.name
                },
                "data": tables_data
            }

            # Serializa e compacta com GZIP
            json_bytes = json.dumps(backup_payload, ensure_ascii=False, default=_json_serial).encode('utf-8')
            with gzip.open(file_path, 'wb') as f:
                f.write(json_bytes)

            file_size = os.path.getsize(file_path)
            logger.info(f"[Backup] Backup gerado com sucesso: {filename} ({file_size} bytes, {sum(counts.values())} registros)")

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
                "gdrive": gdrive_status
            }

        except Exception as e:
            logger.error(f"[Backup] Falha ao criar backup: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    @classmethod
    def restore_backup(cls, file_stream_or_path):
        """
        Restaura o banco de dados a partir de um arquivo .json.gz ou .json.
        Executa tudo dentro de uma transação atômica e atualiza sequences no Postgres.
        """
        try:
            # Identifica se é caminho ou stream
            if isinstance(file_stream_or_path, str):
                if file_stream_or_path.endswith('.gz'):
                    with gzip.open(file_stream_or_path, 'rb') as f:
                        raw_data = f.read().decode('utf-8')
                else:
                    with open(file_stream_or_path, 'r', encoding='utf-8') as f:
                        raw_data = f.read()
            else:
                # É um file-like object (Upload)
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

            # Executa a restauração dentro de transação segura
            for key, model in ORDERED_MODELS:
                rows = data.get(key, [])
                restored_count = 0
                for row_dict in rows:
                    rec_id = row_dict.get('id')
                    existing = model.query.get(rec_id) if rec_id else None

                    # Converte campos de data/datetime
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

            return {
                "success": True,
                "message": "Backup restaurado com sucesso!",
                "stats": stats,
                "metadata": payload.get("metadata", {})
            }

        except Exception as e:
            db.session.rollback()
            logger.error(f"[Backup Restore] Erro fatal na restauração: {e}", exc_info=True)
            return {"success": False, "error": f"Falha na restauração: {str(e)}"}

    @classmethod
    def list_backups(cls):
        """Lista todos os arquivos de backup salvos localmente."""
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

                backups.append({
                    "filename": fn,
                    "path": fp,
                    "size_display": size_display,
                    "size_bytes": st.st_size,
                    "created_at": mod_time
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

            # Testa listagem básica
            about = drive_service.about().get(fields="user").execute()
            user_email = about.get('user', {}).get('emailAddress', creds_dict.get('client_email', 'Service Account'))

            # Se folder_id foi informado, valida acesso à pasta
            folder_name = "Raiz do Drive"
            if folder_id:
                folder_meta = drive_service.files().get(fileId=folder_id, fields="id, name, mimeType").execute()
                folder_name = folder_meta.get('name', folder_id)

            return True, f"Conexão com Google Drive bem-sucedida! Autenticado como: {user_email}. Pasta alvo: '{folder_name}'."

        except json.JSONDecodeError:
            return False, "O texto fornecido não é um JSON válido. Cole o arquivo JSON completo gerado no Google Cloud Console."
        except Exception as e:
            return False, f"Falha na autenticação do Google Drive: {str(e)}"
