import json
from flask import request, jsonify
from app.api import bp
from app.models import MessageLog, Client
from app import db
from app.utils.waha import WahaAPI
from app.utils.ai_handler import AIHandler

@bp.route('/webhook/waha', methods=['POST'])
def waha_webhook():
    '''
    Endpoint for receiving event updates from WAHA API.
    Example Events: MESSAGES_UPDATE (read/delivered statuses), MESSAGES_UPSERT
    '''
    data = request.get_json(force=True)
    if not data:
        return jsonify({"status": "no data"}), 400

    # Handle status updates (e.g., delivered, read, error)
    if data.get('event') == 'messages.update':
        updates = data.get('data', [])
        for update in updates:
            # Depending on how the WAHA API maps it, we might check message ID
            # Here we just save the raw log for demonstration if needed, or match to MessageLog ID if we stored it
            # Future: Find message log by API message ID and update status
            pass
            
    # Handle incoming messages
    if data.get('event') in ['message', 'message.any']:
        payload = data.get('payload', {})
        from_phone = payload.get('from', '')
        body = payload.get('body', '')
        is_from_me = payload.get('fromMe', False)
        
        if not is_from_me and body:
            # Identify the client by phone
            clean_phone = from_phone.split('@')[0]
            client = Client.query.filter(Client.phone.contains(clean_phone[-8:])).first()
            
            if client:
                # Generate AI Reply
                ai_reply, error = AIHandler.generate_reply(body)
                
                if ai_reply:
                    # Send it back
                    success, resp = WahaAPI.send_text(client.phone, ai_reply)
                    
                    # Log the reply
                    log = MessageLog(
                        client_id=client.id,
                        user_id=None, # System/AI
                        content=ai_reply,
                        channel='waha_api',
                        status='sent' if success else 'error',
                        api_response=json.dumps(resp) if success else str(resp)
                    )
                    db.session.add(log)
                    db.session.commit()

    return jsonify({"status": "received"}), 200

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
