import os
import logging
from redis import Redis, ConnectionPool
from rq import Queue
from flask import current_app

logger = logging.getLogger(__name__)

_redis_pool = None
_redis_client = None

def get_redis_url():
    """Obtém a URL do Redis a partir das configurações do Flask ou variáveis de ambiente."""
    try:
        if current_app and 'REDIS_URL' in current_app.config:
            return current_app.config['REDIS_URL']
    except RuntimeError:
        pass
    return os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

def get_redis_connection():
    """Retorna uma instância de cliente Redis conectada via pool de conexões."""
    global _redis_pool, _redis_client
    if _redis_client is None:
        url = get_redis_url()
        _redis_pool = ConnectionPool.from_url(url, decode_responses=True, socket_timeout=5, socket_connect_timeout=5)
        _redis_client = Redis(connection_pool=_redis_pool)
    return _redis_client

def get_queue(name='whatsapp_messages'):
    """Retorna uma fila RQ configurada para o nome especificado."""
    conn = get_redis_connection()
    return Queue(name, connection=conn)

def is_duplicate_message(msg_id: str, ttl: int = 600) -> bool:
    """
    Verifica e registra se a mensagem já foi recebida/processada usando SET NX atômico do Redis.
    Retorna True se for duplicada (já existia no Redis).
    Retorna False se for nova (inserida com sucesso no Redis).
    """
    if not msg_id:
        return False
    
    try:
        conn = get_redis_connection()
        key = f"crm:wa:processed:{msg_id}"
        # set with nx=True and ex=ttl retorna True se chave foi criada, None/False se já existia
        was_set = conn.set(key, "1", ex=ttl, nx=True)
        if not was_set:
            logger.info(f"[Deduplication] Mensagem duplicada ignorada: ID={msg_id}")
            return True
        return False
    except Exception as e:
        logger.warning(f"[Deduplication] Falha ao verificar duplicidade no Redis para ID={msg_id}: {e}")
        # Em caso de falha de conexão com Redis, não descartamos a mensagem
        return False

def check_redis_health() -> bool:
    """Verifica conectividade com o Redis."""
    try:
        conn = get_redis_connection()
        return bool(conn.ping())
    except Exception:
        return False
