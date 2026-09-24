"""
Módulo de Agregação Temporal e Debounce de Mensagens (WhatsApp Buffer).

Responsabilidades:
1. Retenção Temporária (Buffer): Armazena mensagens consecutivas no Redis
   durante uma janela de silêncio (ex: 12 segundos) antes de processar.
2. Agrupamento Semântico: Concatena mensagens picadas ("Oi", "tudo bem?", "quanto custa?")
   em um bloco unificado de contexto antes de enviar para o LLM.
3. Despacho Autônomo e Confiável: Agenda a execução tanto no RQ (Redis Queue)
   quanto via Timer em Thread Daemon em segundo plano, garantindo processamento
   mesmo se nenhum RQ worker externo estiver rodando.
4. Mutex e Idempotência: Invalidação de batches obsoletos por tokens únicos
   e locks atômicos no Redis para evitar processamentos duplicados.
"""

import json
import logging
import threading
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


def _run_autonomous_buffer_dispatch(chat_id: str, batch_token: str, instance_id: str = None):
    """
    Executado após o término da janela de silêncio (debounce) por uma thread daemon autônoma.
    
    Garante que a resposta ao cliente seja gerada pela IA e enviada via WAHA MESMO se
    não houver nenhum worker externo do RQ em execução no ambiente.
    """
    try:
        from app.tasks.whatsapp import process_buffered_whatsapp_messages
        process_buffered_whatsapp_messages(chat_id, batch_token, instance_id)
    except Exception as e:
        logger.error(f"[Buffer Dispatcher] Erro ao processar lote para '{chat_id}': {e}", exc_info=True)


def _schedule_autonomous_fallback(chat_id: str, batch_token: str, delay_seconds: int, instance_id: str = None):
    """
    Agenda um timer daemon em background no Python com pequena margem de segurança.
    
    Se o cliente enviar novas mensagens antes do timer expirar, o token no Redis é
    sobrescrito e este timer é descartado de forma limpa pelo `is_valid_batch`.
    """
    try:
        # Adiciona 0.3s de margem para garantir que a janela de debounce fechou completamente
        t = threading.Timer(
            delay_seconds + 0.3,
            _run_autonomous_buffer_dispatch,
            kwargs={"chat_id": chat_id, "batch_token": batch_token, "instance_id": instance_id}
        )
        t.daemon = True
        t.name = f"wa-debounce-{batch_token}"
        t.start()
        logger.info(f"[Buffer] Dispatcher autônomo agendado para '{chat_id}' em {delay_seconds + 0.3:.1f}s.")
    except Exception as e:
        logger.warning(f"[Buffer] Não foi possível agendar timer em thread para '{chat_id}': {e}")


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
    o processamento garantido tanto via RQ quanto via timer autônomo em thread.
    
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

    # 1. Agenda no RQ (se houver workers externos em execução)
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
        logger.warning(f"[Buffer] RQ indisponível para '{chat_id}' (usando fallback autônomo): {e}")

    # 2. Agenda fallback autônomo em thread para garantia total de execução sem RQ
    _schedule_autonomous_fallback(chat_id, batch_token, delay_seconds, instance_id)

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
