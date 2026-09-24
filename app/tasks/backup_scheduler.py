import time
import logging
import threading
from datetime import datetime
from flask import current_app

logger = logging.getLogger(__name__)

_scheduler_thread = None
_scheduler_running = False

def check_and_run_scheduled_backup(app):
    """Verifica as configurações do banco e executa o backup automático se a janela coincidir."""
    with app.app_context():
        try:
            from app.models import Setting
            from app.utils.backup_manager import BackupManager

            enabled = Setting.get('backup_auto_enabled', 'false').lower() in ('true', '1')
            if not enabled:
                return

            scheduled_time = Setting.get('backup_time', '03:00').strip() # HH:MM
            now = datetime.now()
            current_hh_mm = now.strftime('%H:%M')

            # Verifica se está no minuto agendado
            if current_hh_mm != scheduled_time:
                return

            # Checa se já rodou hoje para não rodar múltiplas vezes no mesmo minuto
            last_run = Setting.get('backup_last_auto_date', '')
            today_str = now.strftime('%Y-%m-%d')
            if last_run == today_str:
                return

            frequency = Setting.get('backup_frequency', 'daily')
            if frequency == 'weekly' and now.weekday() != 6: # 6 = Domingo
                return

            logger.info(f"[Backup Scheduler] Iniciando backup automático programado ({frequency} às {scheduled_time})...")
            dest = Setting.get('backup_destination', 'both')
            upload_gdrive = dest in ('gdrive', 'both') or Setting.get('gdrive_enabled', 'false').lower() in ('true', '1')

            result = BackupManager.create_backup(destination=dest, upload_gdrive=upload_gdrive)
            if result.get('success'):
                Setting.set('backup_last_auto_date', today_str)
                logger.info(f"[Backup Scheduler] Backup automático concluído com sucesso: {result.get('filename')}")
            else:
                logger.error(f"[Backup Scheduler] Falha no backup automático: {result.get('error')}")

        except Exception as e:
            logger.error(f"[Backup Scheduler] Erro durante verificação de backup: {e}", exc_info=True)


def _scheduler_loop(app):
    global _scheduler_running
    logger.info("[Backup Scheduler] Thread de agendamento de backups iniciada.")
    while _scheduler_running:
        try:
            check_and_run_scheduled_backup(app)
        except Exception as e:
            logger.error(f"[Backup Scheduler Loop] Erro: {e}")
        # Dorme por 50 segundos para verificar o próximo minuto
        time.sleep(50)


def start_backup_scheduler(app):
    """Inicia a thread daemon de agendamento se ainda não estiver ativa."""
    global _scheduler_thread, _scheduler_running
    if _scheduler_running:
        return

    _scheduler_running = True
    _scheduler_thread = threading.Thread(target=_scheduler_loop, args=(app,), daemon=True, name="BackupSchedulerThread")
    _scheduler_thread.start()
