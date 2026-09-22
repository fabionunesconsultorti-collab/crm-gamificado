import json
import logging
import time
from datetime import datetime, timezone
from flask import current_app

logger = logging.getLogger(__name__)

def _extract_message_id(payload):
    """Extrai o ID da mensagem com suporte a string ou dicionário de serialização do WAHA."""
    raw_id = payload.get('id') or payload.get('message_id')
    if isinstance(raw_id, dict):
        return raw_id.get('_serialized') or raw_id.get('id') or str(raw_id)
    return str(raw_id) if raw_id else None

def _clean_phone_number(raw_phone):
    """Limpa e formata o número do remetente."""
    if not raw_phone:
        return ""
    # Remove sufixos como @c.us ou @s.whatsapp.net se presentes
    phone_clean = raw_phone.split('@')[0]
    return ''.join(filter(str.isdigit, phone_clean))

def _do_process_whatsapp_message(payload, event=None, instance_id=None):
    """Execução interna do processamento da mensagem dentro do contexto do Flask."""
    from app import db
    from app.models import Client, MessageLog
    from app.utils.ai_handler import AIHandler
    from app.utils.waha import WahaAPI

    start_time = time.time()
    msg_id = _extract_message_id(payload)
    from_raw = payload.get('from', '')
    body = payload.get('body', '')
    is_from_me = payload.get('fromMe', False)
    participant = payload.get('participant')
    is_group = '@g.us' in from_raw or bool(participant) or payload.get('isGroup', False)
    is_broadcast = '@broadcast' in from_raw or from_raw == 'status@broadcast'

    logger.info(f"[Task WhatsApp] Iniciando processamento de mensagem: ID={msg_id}, From={from_raw}, FromMe={is_from_me}, Group={is_group}")

    # 1. Filtros de descarte de mensagens
    if is_from_me:
        logger.info(f"[Task WhatsApp] Mensagem enviada pelo próprio número (fromMe=True). Ignorando: ID={msg_id}")
        return {"status": "ignored", "reason": "sent_by_me", "message_id": msg_id}

    if is_group:
        logger.info(f"[Task WhatsApp] Mensagem proveniente de grupo de WhatsApp. Ignorando: ID={msg_id}")
        return {"status": "ignored", "reason": "group_message", "message_id": msg_id}

    if is_broadcast:
        logger.info(f"[Task WhatsApp] Mensagem de broadcast/status ignorada: ID={msg_id}")
        return {"status": "ignored", "reason": "broadcast", "message_id": msg_id}

    if not body or not body.strip():
        logger.info(f"[Task WhatsApp] Mensagem sem conteúdo de texto. Ignorando: ID={msg_id}")
        return {"status": "ignored", "reason": "empty_body", "message_id": msg_id}

    if not from_raw:
        logger.warning(f"[Task WhatsApp] Mensagem sem campo 'from'. Ignorando: ID={msg_id}")
        return {"status": "ignored", "reason": "missing_from", "message_id": msg_id}

    clean_digits = _clean_phone_number(from_raw)
    
    # 2. Localização do cliente no banco de dados (por sufixo de 8 ou 9 dígitos)
    client = None
    if len(clean_digits) >= 8:
        phone_suffix = clean_digits[-8:]
        client = Client.query.filter(Client.phone.contains(phone_suffix)).first()
        if client:
            logger.info(f"[Task WhatsApp] Cliente identificado: ID={client.id}, Nome='{client.name}', Telefone='{client.phone}'")
        else:
            logger.info(f"[Task WhatsApp] Telefone {clean_digits} não cadastrado na base de clientes.")

    # 3. Geração de resposta via Inteligência Artificial
    ai_start = time.time()
    try:
        reply_text, ai_error = AIHandler.generate_reply(body.strip())
        ai_duration = round((time.time() - ai_start) * 1000, 2)
        if ai_error:
            logger.warning(f"[Task WhatsApp] Aviso/Erro na geração da IA ({ai_duration}ms): {ai_error}")
        else:
            logger.info(f"[Task WhatsApp] IA gerou resposta em {ai_duration}ms: '{reply_text[:60]}...'")
    except Exception as e:
        ai_duration = round((time.time() - ai_start) * 1000, 2)
        logger.error(f"[Task WhatsApp] Exceção crítica na IA ({ai_duration}ms): {e}", exc_info=True)
        reply_text = "Olá! Recebemos sua mensagem e um de nossos atendentes entrará em contato em instantes."

    if not reply_text or not reply_text.strip():
        reply_text = "Olá! Recebemos sua mensagem e entraremos em contato em breve."

    # 4. Envio da resposta via WAHA API
    send_start = time.time()
    success, api_response = False, None
    try:
        # Garante destino com formato compatível com o WAHA (geralmente o próprio from_raw ou telefone limpo)
        target_chat_id = from_raw if '@' in from_raw else f"{clean_digits}@c.us"
        success, api_response = WahaAPI.send_text(target_chat_id, reply_text, instance_id=instance_id)
        send_duration = round((time.time() - send_start) * 1000, 2)
        logger.info(f"[Task WhatsApp] Envio WAHA ({send_duration}ms): Sucesso={success}")
    except Exception as e:
        send_duration = round((time.time() - send_start) * 1000, 2)
        logger.error(f"[Task WhatsApp] Erro ao enviar mensagem via WAHA ({send_duration}ms): {e}", exc_info=True)
        api_response = {"error": str(e)}

    # 5. Registro de auditoria no banco de dados (MessageLog)
    try:
        raw_response_str = json.dumps(api_response) if isinstance(api_response, (dict, list)) else str(api_response)
        log = MessageLog(
            client_id=client.id if client else None,
            user_id=None,
            content=reply_text,
            channel='waha_api',
            status='sent' if success else 'error',
            timestamp=datetime.now(timezone.utc),
            api_response=raw_response_str,
            waha_instance_id=instance_id
        )
        db.session.add(log)
        db.session.commit()
        logger.info(f"[Task WhatsApp] Log de mensagem gravado no banco: ID={log.id}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"[Task WhatsApp] Falha ao persistir MessageLog no banco: {e}", exc_info=True)

    total_duration = round((time.time() - start_time) * 1000, 2)
    logger.info(f"[Task WhatsApp] Processamento concluído em {total_duration}ms para ID={msg_id}")

    return {
        "status": "completed",
        "message_id": msg_id,
        "sent": success,
        "reply": reply_text,
        "client_id": client.id if client else None,
        "duration_ms": total_duration
    }

def process_whatsapp_message(payload, event=None, instance_id=None):
    """
    Função principal executada pelo RQ Worker.
    Garante que o contexto da aplicação Flask esteja ativo e configurado.
    """
    try:
        from flask import current_app
        if current_app:
            return _do_process_whatsapp_message(payload, event, instance_id)
    except RuntimeError:
        pass

    # Se estiver rodando isolado no worker sem contexto Flask pré-estabelecido
    from app import create_app
    flask_app = create_app()
    with flask_app.app_context():
        return _do_process_whatsapp_message(payload, event, instance_id)
