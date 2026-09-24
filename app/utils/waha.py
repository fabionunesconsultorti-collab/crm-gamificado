"""
Módulo de Integração com a API do WAHA (WhatsApp HTTP API).

Responsabilidades:
1. Gerenciamento de Sessões: Inicialização, logout, verificação de status e leitura de QR code.
2. Sincronização Automática de Webhook (ensure_webhook): Garante que a sessão ativa no WAHA
   esteja configurada para encaminhar eventos de mensagem para o endpoint do CRM.
3. Comunicação Bidirecional: Envio de texto, ativação/desativação de presença ('digitando...')
   e confirmação visual de leitura (seen).
4. Resolução Dinâmica de Rede: Resolução de IPs e URLs compatíveis com Docker e rede local.
"""

import requests
import json
from app.models import WahaInstance
from app.utils.network import get_connected_ip, resolve_instance_api_url

class WahaAPI:
    @staticmethod
    def get_settings(instance_id=None):
        instance = None
        if instance_id is not None:
            if isinstance(instance_id, int) or (isinstance(instance_id, str) and instance_id.isdigit()):
                instance = WahaInstance.query.get(int(instance_id))
            elif isinstance(instance_id, str):
                instance = WahaInstance.query.filter_by(session_name=instance_id).first()

        if not instance:
            instance = WahaInstance.query.filter_by(is_default=True).first()
            if not instance:
                instance = WahaInstance.query.first() # Fallback
                
        if instance:
            raw_url = instance.api_url.rstrip('/') if instance.api_url else ''
            resolved_url = resolve_instance_api_url(raw_url)
            
            # Se a URL foi corrigida de um IP inválido (como 192.168.1.44), persiste no banco
            if resolved_url != raw_url and raw_url:
                try:
                    from app import db
                    instance.api_url = resolved_url
                    db.session.commit()
                except Exception:
                    pass

            return {
                'id': instance.id,
                'api_url': resolved_url,
                'api_key': instance.api_key or '',
                'session_name': instance.session_name or 'default',
                'waha_api_url': resolved_url,
                'waha_api_key': instance.api_key or '',
                'waha_session_name': instance.session_name or 'default',
                'waha_instance': instance.session_name or 'default'
            }
        
        # Fallback para configurações globais na tabela Setting (waha_* e legados evo_*)
        from app.models import Setting
        api_url = Setting.get('waha_api_url') or Setting.get('evo_api_url')
        api_key = Setting.get('waha_api_key') or Setting.get('evo_api_key', '')
        session_name = Setting.get('waha_session_name') or Setting.get('waha_instance') or Setting.get('evo_instance', 'default')

        connected_ip = get_connected_ip()
        final_url = resolve_instance_api_url(api_url) if api_url else f'http://{connected_ip}:3000'
        return {
            'id': None,
            'api_url': final_url,
            'api_key': api_key or '',
            'session_name': session_name or 'default',
            'waha_api_url': final_url,
            'waha_api_key': api_key or '',
            'waha_session_name': session_name or 'default',
            'waha_instance': session_name or 'default'
        }

    @staticmethod
    def get_webhook_url():
        """
        Retorna a URL onde o container WAHA deve enviar os webhooks para o backend do CRM.
        """
        from app.models import Setting
        custom_url = Setting.get('whatsapp_webhook_url')
        if custom_url and custom_url.strip():
            return custom_url.strip()
        # Default para container na rede docker interna falando com o host
        return "http://172.18.0.1:5000/api/webhook/whatsapp"

    @staticmethod
    def is_configured(instance_id=None):
        cfg = WahaAPI.get_settings(instance_id)
        return bool(cfg['api_url'] and cfg['session_name'])

    @staticmethod
    def get_headers(instance_id=None):
        cfg = WahaAPI.get_settings(instance_id)
        headers = {'Content-Type': 'application/json'}
        if cfg['api_key']:
            headers['X-Api-Key'] = cfg['api_key'] # WAHA usa X-Api-Key
        return headers

    @staticmethod
    def send_text(phone_number, text, instance_id=None):
        cfg = WahaAPI.get_settings(instance_id)
        if not WahaAPI.is_configured(instance_id):
            return False, "WAHA API não configurada."

        raw_phone = str(phone_number).strip()
        if '@' in raw_phone:
            chat_id = raw_phone
        else:
            clean_phone = ''.join(filter(str.isdigit, raw_phone))
            chat_id = f"{clean_phone}@c.us"
        
        url = f"{cfg['api_url']}/api/sendText"
        payload = {
            "session": cfg['session_name'],
            "chatId": chat_id,
            "text": text
        }
        
        try:
            response = requests.post(url, headers=WahaAPI.get_headers(instance_id), json=payload, timeout=15)
            if response.status_code in [200, 201]:
                return True, response.json()
            else:
                return False, f"Status {response.status_code}: {response.text}"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def start_typing(phone_or_chat_id, instance_id=None):
        """Ativa o indicador 'digitando...' (presença) no chat do WhatsApp."""
        cfg = WahaAPI.get_settings(instance_id)
        if not WahaAPI.is_configured(instance_id):
            return False, "WAHA API não configurada."

        raw = str(phone_or_chat_id)
        chat_id = raw if '@' in raw else f"{''.join(filter(str.isdigit, raw))}@c.us"
        url = f"{cfg['api_url']}/api/startTyping"
        payload = {"session": cfg['session_name'], "chatId": chat_id}

        try:
            resp = requests.post(url, headers=WahaAPI.get_headers(instance_id), json=payload, timeout=5)
            return resp.status_code in [200, 201], resp.text
        except Exception as e:
            return False, str(e)

    @staticmethod
    def stop_typing(phone_or_chat_id, instance_id=None):
        """Desativa o indicador 'digitando...' no chat do WhatsApp."""
        cfg = WahaAPI.get_settings(instance_id)
        if not WahaAPI.is_configured(instance_id):
            return False, "WAHA API não configurada."

        raw = str(phone_or_chat_id)
        chat_id = raw if '@' in raw else f"{''.join(filter(str.isdigit, raw))}@c.us"
        url = f"{cfg['api_url']}/api/stopTyping"
        payload = {"session": cfg['session_name'], "chatId": chat_id}

        try:
            resp = requests.post(url, headers=WahaAPI.get_headers(instance_id), json=payload, timeout=5)
            return resp.status_code in [200, 201], resp.text
        except Exception as e:
            return False, str(e)

    @staticmethod
    def send_seen(phone_or_chat_id, message_id=None, instance_id=None):
        """Marca as mensagens como vistas/lidas no WhatsApp."""
        cfg = WahaAPI.get_settings(instance_id)
        if not WahaAPI.is_configured(instance_id):
            return False, "WAHA API não configurada."

        raw = str(phone_or_chat_id)
        chat_id = raw if '@' in raw else f"{''.join(filter(str.isdigit, raw))}@c.us"
        url = f"{cfg['api_url']}/api/sendSeen"
        payload = {"session": cfg['session_name'], "chatId": chat_id}
        if message_id:
            payload["messageId"] = message_id

        try:
            resp = requests.post(url, headers=WahaAPI.get_headers(instance_id), json=payload, timeout=5)
            return resp.status_code in [200, 201], resp.text
        except Exception as e:
            return False, str(e)


    @staticmethod
    def get_connection_state(instance_id=None):
        cfg = WahaAPI.get_settings(instance_id)
        if not WahaAPI.is_configured(instance_id):
            return False, "WAHA API não configurada."

        # WAHA v2/v3 usa GET /api/sessions/{session}
        url = f"{cfg['api_url']}/api/sessions/{cfg['session_name']}"
        
        try:
            response = requests.get(url, headers=WahaAPI.get_headers(instance_id), timeout=10)
            if response.status_code == 200:
                data = response.json()
                # Mapeamento de WAHA para o formato que o frontend espera
                # WAHA States: STOPPED, STARTING, SCAN_QR_CODE, WORKING, FAILED
                state = data.get('status', 'STOPPED')
                
                # Mapear estados WAHA para a interface (open, close, connecting, not_found):
                mapped_state = 'close'
                if state == 'WORKING': mapped_state = 'open'
                elif state == 'SCAN_QR_CODE': mapped_state = 'close' # 'close' faz o JS mostrar o botão "Gerar QR"
                elif state == 'STARTING': mapped_state = 'connecting'
                
                return True, {'instance': {'state': mapped_state, 'waha_status': state}}
            elif response.status_code == 404:
                return True, {'instance': {'state': 'not_found'}}
            elif response.status_code == 422:
                # Caso específico do WAHA Core que só aceita 'default'
                return False, "Sua instância WAHA Core suporta apenas a sessão 'default'. Altere o nome da instância para 'default'."
            else:
                return False, response.text
        except requests.exceptions.ConnectionError:
            return False, f"Falha de conexão com WAHA em {cfg['api_url']}. Verifique se o container está em execução."
        except requests.exceptions.Timeout:
            return False, f"Tempo limite excedido ao conectar ao WAHA em {cfg['api_url']}."
        except Exception as e:
            return False, str(e)

    @staticmethod
    def create_instance(instance_id=None):
        """Inicia uma sessão na WAHA com webhooks configurados automaticamente"""
        cfg = WahaAPI.get_settings(instance_id)
        if not WahaAPI.is_configured(instance_id):
            return False, "WAHA API não configurada."
            
        webhook_url = WahaAPI.get_webhook_url()
        url = f"{cfg['api_url']}/api/sessions"
        payload = {
            "name": cfg['session_name'],
            "start": True,
            "config": {
                "proxy": None,
                "webhooks": [
                    {
                        "url": webhook_url,
                        "events": ["message", "message.any"]
                    }
                ]
            }
        }
        
        try:
            response = requests.post(url, headers=WahaAPI.get_headers(instance_id), json=payload, timeout=20)
            if response.status_code in [200, 201]:
                return True, response.json()
            else:
                # Se já existir, tenta assegurar que o webhook está configurado
                WahaAPI.ensure_webhook(instance_id)
                return False, response.text
        except Exception as e:
            return False, str(e)

    @staticmethod
    def ensure_webhook(instance_id=None):
        """
        Garante que a sessão ativa no WAHA esteja despachando webhooks para o backend do CRM.
        Consulta a sessão atual; se os webhooks estiverem ausentes ou divergentes,
        aplica a configuração via PUT /api/sessions/{session}.
        """
        cfg = WahaAPI.get_settings(instance_id)
        if not WahaAPI.is_configured(instance_id):
            return False, "WAHA API não configurada."

        session_name = cfg['session_name']
        webhook_url = WahaAPI.get_webhook_url()
        events = ["message", "message.any"]
        headers = WahaAPI.get_headers(instance_id)

        url = f"{cfg['api_url']}/api/sessions/{session_name}"
        try:
            get_resp = requests.get(url, headers=headers, timeout=10)
            if get_resp.status_code != 200:
                return False, f"Sessão '{session_name}' não encontrada ou inativa no WAHA."

            data = get_resp.json()
            config = data.get('config') or {}
            existing_webhooks = config.get('webhooks') or []

            # Verifica se já possui o webhook desejado
            has_matching = any(
                w.get('url') == webhook_url and 'message' in (w.get('events') or [])
                for w in existing_webhooks
            )

            if has_matching:
                return True, f"Webhook já configurado em {webhook_url}"

            # Atualiza a sessão com o webhook
            put_payload = {
                "name": session_name,
                "config": {
                    "webhooks": [
                        {"url": webhook_url, "events": events}
                    ]
                }
            }
            put_resp = requests.put(url, headers=headers, json=put_payload, timeout=15)
            if put_resp.status_code in [200, 201]:
                return True, f"Webhook registrado com sucesso: {webhook_url}"
            else:
                return False, f"Falha ao registrar webhook no WAHA ({put_resp.status_code}): {put_resp.text}"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def connect_instance(instance_id=None):
        """Obtém o QR Code da WAHA"""
        cfg = WahaAPI.get_settings(instance_id)
        if not WahaAPI.is_configured(instance_id):
            return False, "WAHA API não configurada."

        # WAHA retorna o QR code diretamente no endpoint ou como base64
        url = f"{cfg['api_url']}/api/{cfg['session_name']}/auth/qr"
        
        try:
            # Pedindo especificamente JSON se possível, ou capturando a imagem
            params = {"format": "json"} 
            response = requests.get(url, headers=WahaAPI.get_headers(instance_id), params=params, timeout=20)
            
            if response.status_code == 200:
                # WAHA pode retornar {"qr": "..."} ou a imagem diretamente
                if 'application/json' in response.headers.get('Content-Type', ''):
                    data = response.json()
                    qr_code = data.get('qr')
                    return True, {'base64': qr_code}
                else:
                    # Se for imagem, o ideal seria converter para base64 para o frontend
                    import base64
                    encoded = base64.b64encode(response.content).decode('ascii')
                    return True, {'base64': encoded}
            else:
                return False, f"Erro ao obter QR: {response.status_code}"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def list_sessions(instance_id=None):
        """Lista todas as sessões configuradas na WAHA"""
        cfg = WahaAPI.get_settings(instance_id)
        if not cfg['api_url']:
            return False, "URL da API não configurada."
            
        url = f"{cfg['api_url']}/api/sessions"
        try:
            response = requests.get(url, headers=WahaAPI.get_headers(instance_id), timeout=10)
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, response.text
        except Exception as e:
            return False, str(e)

    @staticmethod
    def logout_instance(instance_id=None):
        """Para/Deleta a sessão na WAHA"""
        cfg = WahaAPI.get_settings(instance_id)
        if not WahaAPI.is_configured(instance_id):
            return False, "WAHA API não configurada."

        # DELETE /api/sessions/{session} remove a sessão e os dados
        url = f"{cfg['api_url']}/api/sessions/{cfg['session_name']}"
        try:
            response = requests.delete(url, headers=WahaAPI.get_headers(instance_id), timeout=10)
            if response.status_code in [200, 201, 204]:
                return True, {"message": "Sessão encerrada"}
            else:
                return False, response.text
        except Exception as e:
            return False, str(e)
