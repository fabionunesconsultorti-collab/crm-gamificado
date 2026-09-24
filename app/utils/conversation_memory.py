import json
import logging
from datetime import datetime, timezone
from app.tasks.queue import get_redis_connection

logger = logging.getLogger(__name__)

REDIS_PREFIX_HISTORY = "crm:wa:history"
DEFAULT_HISTORY_TURNS = 8
DEFAULT_TTL_HOURS = 4


def get_history_settings() -> tuple[int, int]:
    """Obtém configurações de histórico conversacional (limite de turnos e TTL em segundos)."""
    turns = DEFAULT_HISTORY_TURNS
    ttl_seconds = DEFAULT_TTL_HOURS * 3600

    try:
        from app.models import Setting
        turns_val = Setting.get('whatsapp_history_turns')
        if turns_val is not None and str(turns_val).strip().isdigit():
            turns = max(2, min(int(turns_val), 30))

        ttl_val = Setting.get('whatsapp_history_ttl_hours')
        if ttl_val is not None and str(ttl_val).strip().isdigit():
            hours = max(1, min(int(ttl_val), 48))
            ttl_seconds = hours * 3600
    except Exception as e:
        logger.warning(f"[ConversationMemory] Falha ao ler configurações de histórico: {e}")

    return turns, ttl_seconds


class ConversationMemory:
    """
    Gerenciador de memória de conversação multi-turno armazenado no Redis.
    Mantém histórico deslizante de mensagens de usuário e respostas do assistente.
    """

    @staticmethod
    def get_context_messages(chat_id: str) -> list[dict]:
        """
        Retorna o histórico da conversa no formato aceito pelo Ollama/OpenAI API:
        [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
        """
        if not chat_id:
            return []

        conn = get_redis_connection()
        history_key = f"{REDIS_PREFIX_HISTORY}:{chat_id}"
        max_turns, _ = get_history_settings()

        try:
            # Pega os últimos 'max_turns' do Redis
            raw_items = conn.lrange(history_key, -max_turns, -1)
            formatted = []
            for item in raw_items:
                try:
                    data = json.loads(item) if isinstance(item, str) else item
                    role = data.get('role')
                    content = data.get('content')
                    if role in ['user', 'assistant'] and content:
                        formatted.append({"role": role, "content": content})
                except Exception:
                    continue
            return formatted
        except Exception as e:
            logger.error(f"[ConversationMemory] Erro ao carregar histórico para '{chat_id}': {e}")
            return []

    @staticmethod
    def record_turn(chat_id: str, user_content: str, assistant_content: str):
        """
        Registra um turno completo (pergunta do usuário + resposta do assistente)
        na lista de memória do Redis e renova o TTL.
        """
        if not chat_id:
            return

        conn = get_redis_connection()
        history_key = f"{REDIS_PREFIX_HISTORY}:{chat_id}"
        max_turns, ttl_seconds = get_history_settings()

        now_iso = datetime.now(timezone.utc).isoformat()
        user_item = json.dumps({"role": "user", "content": user_content.strip(), "timestamp": now_iso})
        assistant_item = json.dumps({"role": "assistant", "content": assistant_content.strip(), "timestamp": now_iso})

        try:
            pipeline = conn.pipeline()
            pipeline.rpush(history_key, user_item, assistant_item)
            # Mantém apenas os últimos (max_turns * 2) registros para não crescer indefinidamente
            pipeline.ltrim(history_key, -(max_turns * 2), -1)
            pipeline.expire(history_key, ttl_seconds)
            pipeline.execute()
            logger.info(f"[ConversationMemory] Turno gravado no histórico de '{chat_id}'. TTL={ttl_seconds}s.")
        except Exception as e:
            logger.error(f"[ConversationMemory] Falha ao persistir turno para '{chat_id}': {e}", exc_info=True)

    @staticmethod
    def clear(chat_id: str):
        """Limpa o histórico de conversa do contato especificado."""
        try:
            conn = get_redis_connection()
            conn.delete(f"{REDIS_PREFIX_HISTORY}:{chat_id}")
            logger.info(f"[ConversationMemory] Histórico apagado para '{chat_id}'.")
        except Exception as e:
            logger.error(f"[ConversationMemory] Erro ao limpar histórico de '{chat_id}': {e}")
