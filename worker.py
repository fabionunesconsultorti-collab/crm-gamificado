#!/usr/bin/env python
import os
import sys
import logging
from rq import Worker, Queue, Connection
from app import create_app
from app.tasks.queue import get_redis_connection

# Configuração de log
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("rq.worker")

# Filas a serem processadas pelo worker
LISTEN_QUEUES = ['whatsapp_messages', 'default']

app = create_app()

def run_worker():
    """Inicializa o worker RQ com o contexto da aplicação Flask."""
    with app.app_context():
        redis_conn = get_redis_connection()
        try:
            redis_conn.ping()
            host = redis_conn.connection_pool.connection_kwargs.get('host', 'unknown')
            port = redis_conn.connection_pool.connection_kwargs.get('port', '6379')
            logger.info(f"[*] Conexão com Redis estabelecida com sucesso ({host}:{port})")
        except Exception as e:
            logger.error(f"[!] Falha ao conectar ao Redis: {e}")
            sys.exit(1)

        logger.info(f"[*] CRM Pro Background Worker iniciado. Monitorando filas: {', '.join(LISTEN_QUEUES)}")
        with Connection(redis_conn):
            worker = Worker(list(map(Queue, LISTEN_QUEUES)))
            worker.work(with_scheduler=True)

if __name__ == '__main__':
    run_worker()
