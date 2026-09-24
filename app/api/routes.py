"""
Endpoints da API REST e Webhooks Externos (CRM Pro).

Responsabilidades:
1. Webhooks do WhatsApp (/api/webhook/whatsapp e aliases):
   - Recepção veloz (<50ms) de mensagens do WAHA.
   - Filtragem de mensagens de broadcast, grupos e eco do próprio remetente (fromMe).
   - Deduplicação atômica no Redis.
   - Envio imediato para o buffer de agregação temporal (debounce).
2. Mensageria Externa (/api/messages/send_automated):
   - Endpoint autenticado para integrações externas (N8N, Zapier, Webhooks).
"""

import json
import logging
from flask import request, jsonify
from app.api import bp
from app.models import MessageLog, Client
from app import db
from app.utils.waha import WahaAPI
from app.utils.ai_handler import AIHandler
from app.tasks.queue import get_queue, is_duplicate_message
from app.tasks.whatsapp import process_whatsapp_message

logger = logging.getLogger(__name__)

@bp.route('/webhook/whatsapp', methods=['POST'])
@bp.route('/webhook/waha', methods=['POST'])
@bp.route('/whatsapp/webhook', methods=['POST'])
@bp.route('/waha/webhook', methods=['POST'])
def whatsapp_webhook():
    '''
    Endpoint assíncrono de alta performance para receber webhooks do WhatsApp (WAHA).
    Responde em menos de 50ms confirmando o recebimento e delega o processamento da IA para o buffer inteligente.
    '''
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"status": "error", "message": "Payload JSON vazio ou inválido"}), 400

    event = data.get('event')
    
    # 1. Trata atualizações de status de mensagem (lida, entregue, etc.)
    if event == 'messages.update':
        updates = data.get('data', [])
        logger.info(f"[Webhook WhatsApp] Atualização de status recebida: {len(updates)} eventos")
        return jsonify({"status": "received", "event": event, "count": len(updates)}), 200

    # 2. Trata mensagens recebidas
    if event in ['message', 'message.any']:
        payload = data.get('payload', {})
        if not payload:
            return jsonify({"status": "ignored", "reason": "empty_payload"}), 200

        is_from_me = payload.get('fromMe', False)
        if is_from_me:
            return jsonify({"status": "ignored", "reason": "sent_by_me"}), 200

        from_raw = payload.get('from', '')
        if '@g.us' in from_raw or payload.get('participant') or payload.get('isGroup', False):
            return jsonify({"status": "ignored", "reason": "group_message"}), 200

        if '@broadcast' in from_raw or from_raw == 'status@broadcast':
            return jsonify({"status": "ignored", "reason": "broadcast"}), 200

        body = payload.get('body', '')
        if not body or not body.strip():
            return jsonify({"status": "ignored", "reason": "empty_body"}), 200

        # Extração de ID para deduplicação
        raw_id = payload.get('id') or payload.get('message_id')
        msg_id = None
        if isinstance(raw_id, dict):
            msg_id = raw_id.get('_serialized') or raw_id.get('id') or str(raw_id)
        elif raw_id:
            msg_id = str(raw_id)

        # Verificação atômica de idempotência no Redis
        if msg_id and is_duplicate_message(msg_id):
            logger.info(f"[Webhook WhatsApp] Mensagem duplicada ignorada: ID={msg_id}")
            return jsonify({"status": "ignored", "reason": "duplicate_message", "message_id": msg_id}), 200

        # Envio para o buffer de agregação temporal (Debounce) via Redis
        try:
            from app.tasks.buffer import add_to_buffer
            session_name = data.get('session') or data.get('instance_id') or payload.get('instance_id') or 'default'
            batch_token, delay = add_to_buffer(chat_id=from_raw, message_payload=payload, instance_id=session_name)

            logger.info(f"[Webhook WhatsApp] Mensagem recebida e retida no buffer: Chat={from_raw}, MsgID={msg_id}, Token={batch_token}, Delay={delay}s, Session={session_name}")
            return jsonify({
                "status": "buffered",
                "chat_id": from_raw,
                "message_id": msg_id,
                "batch_token": batch_token,
                "delay_seconds": delay
            }), 200
        except Exception as e:
            logger.error(f"[Webhook WhatsApp] Erro ao adicionar ao buffer no Redis: {e}", exc_info=True)
            # Retorna 200 para evitar que o WAHA fique reenviando em loop em caso de erro transitório
            return jsonify({
                "status": "error_buffering",
                "error": str(e),
                "message_id": msg_id
            }), 200


    return jsonify({"status": "received", "event": event}), 200

@bp.route('/messages/send_automated', methods=['POST'])
def send_automated_message():
    '''
    Private endpoint to decouple CRM logic from UI, or to be called from N8N/Zapier
    Expects JSON: { "client_id": 123, "text": "Hello [NOME]" }
    '''
    # Basic API Key protection can be added here
    data = request.get_json(force=True)
    client_id = data.get('client_id')
    text = data.get('text')
    user_id = data.get('user_id') # System user triggering this

    if not client_id or not text:
        return jsonify({"error": "Missing client_id or text"}), 400

    from app.models import Client
    client = Client.query.get(client_id)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    # The text MUST arrive interpolated, OR the caller can pass the raw template 
    # but normally the API caller won't. Let's assume text is ready.
    success, api_response = WahaAPI.send_text(client.phone, text)

    # Log it
    log = MessageLog(
        client_id=client.id,
        user_id=user_id,
        content=text,
        channel='waha_api',
        status='sent' if success else 'error',
        api_response=json.dumps(api_response) if isinstance(api_response, dict) else str(api_response)
    )
    db.session.add(log)
    db.session.commit()

    if success:
        return jsonify({"status": "sent", "response": api_response})
    else:
        return jsonify({"error": "WAHA API Failed", "details": api_response}), 500
