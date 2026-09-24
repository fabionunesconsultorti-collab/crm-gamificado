import json
import logging
import time
from datetime import datetime, timezone
from app.tasks.queue import get_redis_connection

logger = logging.getLogger(__name__)

REDIS_LIVE_EVENTS_KEY = "crm:wa:live_pipeline_events"
REDIS_ACTIVE_BATCHES_KEY = "crm:wa:live_active_batches"
MAX_EVENTS_HISTORY = 60

STEP_WEBHOOK = "webhook_received"       # Passo 1: Webhook recebido
STEP_BUFFER = "buffer_debounce"         # Passo 2: Buffer & Debounce Redis
STEP_CONTEXT = "context_building"       # Passo 3: Memória Redis + CRM
STEP_PRESENCE = "presence_active"       # Passo 4: Presença WAHA (Seen + Typing)
STEP_OLLAMA = "ollama_generating"       # Passo 5: Geração de texto no Ollama
STEP_DISPATCH = "waha_dispatched"       # Passo 6: Despacho WAHA e gravação

STEP_METADATA = {
    STEP_WEBHOOK: {"index": 1, "title": "Webhook WAHA", "icon": "fa-inbox"},
    STEP_BUFFER: {"index": 2, "title": "Buffer & Debounce", "icon": "fa-stopwatch"},
    STEP_CONTEXT: {"index": 3, "title": "Formação de Contexto", "icon": "fa-brain"},
    STEP_PRESENCE: {"index": 4, "title": "Presença WAHA", "icon": "fa-keyboard"},
    STEP_OLLAMA: {"index": 5, "title": "Inferência Ollama", "icon": "fa-robot"},
    STEP_DISPATCH: {"index": 6, "title": "Envio & Persistência", "icon": "fa-paper-plane"},
}


class LiveTracker:
    """Rastreador de eventos do fluxo autônomo do Bot para o dashboard em tempo real."""

    @staticmethod
    def emit_step(
        batch_id: str,
        chat_id: str,
        step: str,
        status: str = "active",  # active, completed, error, skipped
        details: dict = None,
        duration_ms: float = None
    ):
        """Emite uma etapa no pipeline em tempo real e armazena no Redis."""
        try:
            conn = get_redis_connection()
            meta = STEP_METADATA.get(step, {"index": 0, "title": step, "icon": "fa-circle"})

            event_data = {
                "id": f"{batch_id}_{step}_{int(time.time() * 1000)}",
                "batch_id": batch_id,
                "chat_id": chat_id,
                "step": step,
                "step_index": meta["index"],
                "step_title": meta["title"],
                "step_icon": meta["icon"],
                "status": status,
                "details": details or {},
                "duration_ms": duration_ms,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "time_str": datetime.now(timezone.utc).strftime("%H:%M:%S")
            }

            serialized = json.dumps(event_data)

            pipeline = conn.pipeline()
            # Adiciona ao histórico geral dos últimos N eventos
            pipeline.lpush(REDIS_LIVE_EVENTS_KEY, serialized)
            pipeline.ltrim(REDIS_LIVE_EVENTS_KEY, 0, MAX_EVENTS_HISTORY - 1)
            pipeline.expire(REDIS_LIVE_EVENTS_KEY, 86400)

            # Atualiza o estado atual do lote ativo
            batch_state_key = f"crm:wa:batch_state:{batch_id}"
            pipeline.set(batch_state_key, serialized, ex=600)
            pipeline.execute()

            logger.debug(f"[LiveTracker] Evento registrado: {step} ({status}) para '{chat_id}' [Batch: {batch_id}]")
            return event_data
        except Exception as e:
            logger.warning(f"[LiveTracker] Erro ao registrar evento no Redis: {e}")
            return None

    @staticmethod
    def get_recent_events(limit: int = 30) -> list[dict]:
        """Obtém os eventos mais recentes do pipeline em ordem cronológica inversa."""
        try:
            conn = get_redis_connection()
            raw_items = conn.lrange(REDIS_LIVE_EVENTS_KEY, 0, limit - 1)
            events = []
            for item in raw_items:
                try:
                    events.append(json.loads(item) if isinstance(item, str) else item)
                except Exception:
                    continue
            return events
        except Exception as e:
            logger.error(f"[LiveTracker] Falha ao ler eventos recentes: {e}")
            return []

    @staticmethod
    def get_active_batches() -> list[dict]:
        """Recupera os lotes que estão sendo processados ou aguardando debounce no momento."""
        try:
            conn = get_redis_connection()
            keys = conn.keys("crm:wa:batch_state:*")
            batches = []
            for key in keys:
                raw = conn.get(key)
                if raw:
                    try:
                        batches.append(json.loads(raw) if isinstance(raw, str) else raw)
                    except Exception:
                        continue
            batches.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            return batches[:10]
        except Exception as e:
            logger.error(f"[LiveTracker] Falha ao recuperar lotes ativos: {e}")
            return []

    @staticmethod
    def get_system_stats() -> dict:
        """Obtém estatísticas em tempo real para os medidores do painel."""
        from app.utils.ai_handler import AIHandler
        from app.utils.waha import WahaAPI
        from app.models import MessageLog, Setting

        # Checa status do Ollama
        ai_cfg = AIHandler.get_config()
        ollama_status = {"online": False, "model": ai_cfg.get("ollama_model", "llama3.2")}
        try:
            info = AIHandler.get_available_models()
            ollama_status["online"] = info.get("online", False)
            ollama_status["models"] = info.get("models", [])
        except Exception:
            pass

        # Checa status do WAHA
        waha_online = False
        try:
            ok, _ = WahaAPI.get_connection_state()
            waha_online = bool(ok)
        except Exception:
            pass

        # Checa status do Redis e contagens
        redis_online = False
        buffer_count = 0
        history_count = 0
        try:
            conn = get_redis_connection()
            redis_online = bool(conn.ping())
            buffer_keys = conn.keys("crm:wa:buffer:*")
            buffer_count = len(buffer_keys)
            history_keys = conn.keys("crm:wa:history:*")
            history_count = len(history_keys)
        except Exception:
            pass

        # Métricas de logs
        total_replies = 0
        try:
            total_replies = MessageLog.query.filter(MessageLog.content.like("[Lote %")).count()
        except Exception:
            pass

        debounce_delay = Setting.get('whatsapp_debounce_delay') or 12
        bot_enabled = Setting.get('whatsapp_bot_enabled')
        is_bot_active = True if bot_enabled is None else str(bot_enabled).lower() in ['true', '1', 'yes']

        return {
            "waha": {"online": waha_online},
            "ollama": ollama_status,
            "redis": {
                "online": redis_online,
                "active_buffers": buffer_count,
                "active_conversations": history_count
            },
            "bot": {
                "active": is_bot_active,
                "debounce_delay": int(debounce_delay),
                "total_batches_processed": total_replies
            }
        }
