import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from app.tasks.queue import get_redis_connection, get_queue

logger = logging.getLogger(__name__)

# Prefixo padrão de chaves Redis
REDIS_PREFIX_BUFFER = "crm:wa:buffer"
REDIS_PREFIX_TIMER = "crm:wa:timer"
REDIS_PREFIX_LOCK = "crm:wa:lock"

DEFAULT_DEBOUNCE_DELAY = 12  # segundos de silêncio para fechar a janela
BUFFER_TTL = 3600  # 1 hora de segurança para mensagens no buffer
TIMER_KEY_TTL = 300  # 5 minutos para o token ativo


def get_debounce_delay() -> int:
    """Obtém o tempo de debounce em segundos configurado no banco de dados."""
    try:
        from app.models import Setting
        val = Setting.get('whatsapp_debounce_delay')
        if val is not None and str(val).strip().isdigit():
            delay = int(val)
            return max(3, min(delay, 120))  # Limites de segurança entre 3s e 120s
    except Exception as e:
        logger.warning(f"[Buffer] Não foi possível ler whatsapp_debounce_delay: {e}")
    return DEFAULT_DEBOUNCE_DELAY


def add_to_buffer(chat_id: str, message_payload: dict, instance_id: str = None) -> tuple[str, int]:
    """
    Adiciona a mensagem ao buffer do Redis para o chat_id especificado e agenda
    um job de processamento no RQ com atraso (debouncing).
    
    Retorna (batch_token, delay_seconds).
    """
    from app.tasks.whatsapp import process_buffered_whatsapp_messages

    conn = get_redis_connection()
    buffer_key = f"{REDIS_PREFIX_BUFFER}:{chat_id}"
    timer_key = f"{REDIS_PREFIX_TIMER}:{chat_id}"

    # Prepara o item serializado com timestamp de recepção
    item = {
        "id": message_payload.get('id') or message_payload.get('message_id') or str(uuid.uuid4()),
        "body": message_payload.get('body', '').strip(),
        "from": message_payload.get('from', chat_id),
        "timestamp": message_payload.get('timestamp') or datetime.now(timezone.utc).isoformat(),
        "instance_id": instance_id or message_payload.get('instance_id')
    }

    # Gera token único para esta versão do batch
    batch_token = uuid.uuid4().hex[:12]

    # Pipeline atômico no Redis para armazenar mensagem e atualizar o timer token
    pipeline = conn.pipeline()
    pipeline.rpush(buffer_key, json.dumps(item))
    pipeline.expire(buffer_key, BUFFER_TTL)
    pipeline.set(timer_key, batch_token, ex=TIMER_KEY_TTL)
    pipeline.execute()

    delay_seconds = get_debounce_delay()

    # Emissão de eventos para o monitor em tempo real
    try:
        from app.utils.live_tracker import LiveTracker, STEP_WEBHOOK, STEP_BUFFER

        # Passo 1: Notifica recepção
        LiveTracker.emit_step(
            batch_id=batch_token,
            chat_id=chat_id,
            step=STEP_WEBHOOK,
            status="completed",
            details={"message": item["body"][:120], "id": item["id"]}
        )
        # Passo 2: Notifica buffer & contagem regressiva
        LiveTracker.emit_step(
            batch_id=batch_token,
            chat_id=chat_id,
            step=STEP_BUFFER,
            status="active",
            details={"delay_seconds": delay_seconds, "latest_text": item["body"][:60]}
        )
    except Exception as e:
        logger.debug(f"[Buffer] Tracker error: {e}")

    # Agenda a execução no RQ com delay
    try:
        queue = get_queue('whatsapp_messages')
        queue.enqueue_in(
            timedelta(seconds=delay_seconds),
            process_buffered_whatsapp_messages,
            chat_id=chat_id,
            batch_token=batch_token,
            instance_id=instance_id,
            job_timeout='3m'
        )
        logger.info(
            f"[Buffer] Mensagem adicionada ao buffer de '{chat_id}'. "
            f"Token={batch_token}, delay={delay_seconds}s. Agendado no RQ."
        )
    except Exception as e:
        logger.error(f"[Buffer] Falha ao enfileirar job atrasado no RQ para '{chat_id}': {e}", exc_info=True)


    return batch_token, delay_seconds


def is_valid_batch(chat_id: str, batch_token: str) -> bool:
    """
    Verifica se o batch_token do job ainda corresponde ao token ativo no Redis.
    Se o cliente enviou novas mensagens enquanto o job esperava, o token foi sobrescrito
    e este job deve ser descartado silenciosamente.
    """
    if not chat_id or not batch_token:
        return False
    try:
        conn = get_redis_connection()
        current_token = conn.get(f"{REDIS_PREFIX_TIMER}:{chat_id}")
        return current_token == batch_token
    except Exception as e:
        logger.error(f"[Buffer] Erro ao validar batch token no Redis: {e}")
        return False


def acquire_chat_lock(chat_id: str, timeout_seconds: int = 30) -> bool:
    """Adquire um mutex lock distribuído no Redis para processamento exclusivo do chat."""
    try:
        conn = get_redis_connection()
        lock_key = f"{REDIS_PREFIX_LOCK}:{chat_id}"
        return bool(conn.set(lock_key, "1", nx=True, ex=timeout_seconds))
    except Exception as e:
        logger.error(f"[Buffer] Erro ao adquirir lock para {chat_id}: {e}")
        return False


def release_chat_lock(chat_id: str):
    """Libera o mutex lock distribuído no Redis."""
    try:
        conn = get_redis_connection()
        conn.delete(f"{REDIS_PREFIX_LOCK}:{chat_id}")
    except Exception as e:
        logger.warning(f"[Buffer] Erro ao liberar lock para {chat_id}: {e}")


def pop_all_buffered_messages(chat_id: str) -> list[dict]:
    """
    Extrai atomicamente todas as mensagens acumuladas no buffer do Redis e limpa a lista.
    """
    conn = get_redis_connection()
    buffer_key = f"{REDIS_PREFIX_BUFFER}:{chat_id}"
    timer_key = f"{REDIS_PREFIX_TIMER}:{chat_id}"

    try:
        pipeline = conn.pipeline()
        pipeline.lrange(buffer_key, 0, -1)
        pipeline.delete(buffer_key)
        pipeline.delete(timer_key)
        results = pipeline.execute()

        raw_messages = results[0] or []
        messages = []
        for raw in raw_messages:
            try:
                messages.append(json.loads(raw) if isinstance(raw, str) else raw)
            except Exception:
                continue

        logger.info(f"[Buffer] Extraídas {len(messages)} mensagens do buffer de '{chat_id}'.")
        return messages
    except Exception as e:
        logger.error(f"[Buffer] Falha ao extrair mensagens do buffer de '{chat_id}': {e}", exc_info=True)
        return []
