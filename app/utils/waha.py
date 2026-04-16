import requests
import json
from app.models import Setting

class WahaAPI:
    @staticmethod
    def get_settings():
        settings_raw = Setting.query.all()
        config = {s.key: s.value for s in settings_raw}
        return {
            'api_url': config.get('evo_api_url', '').rstrip('/'), # Reaproveitando chaves evo_*
            'api_key': config.get('evo_api_key', ''),
            'session_name': config.get('evo_instance', 'default')
        }

    @staticmethod
    def is_configured():
        cfg = WahaAPI.get_settings()
        return bool(cfg['api_url'] and cfg['session_name'])

    @staticmethod
    def get_headers():
        cfg = WahaAPI.get_settings()
        headers = {'Content-Type': 'application/json'}
        if cfg['api_key']:
            headers['X-Api-Key'] = cfg['api_key'] # WAHA usa X-Api-Key
        return headers

    @staticmethod
    def send_text(phone_number, text):
        cfg = WahaAPI.get_settings()
        if not WahaAPI.is_configured():
            return False, "WAHA API não configurada."

        # WAHA usa chatId: 5511999999999@c.us
        clean_phone = ''.join(filter(str.isdigit, str(phone_number)))
        if not clean_phone.endswith('@c.us'):
            chat_id = f"{clean_phone}@c.us"
        else:
            chat_id = clean_phone
        
        url = f"{cfg['api_url']}/api/sendText"
        payload = {
            "session": cfg['session_name'],
            "chatId": chat_id,
            "text": text
        }
        
        try:
            response = requests.post(url, headers=WahaAPI.get_headers(), json=payload, timeout=15)
            if response.status_code in [200, 201]:
                return True, response.json()
            else:
                return False, f"Status {response.status_code}: {response.text}"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def get_connection_state():
        cfg = WahaAPI.get_settings()
        if not WahaAPI.is_configured():
            return False, "WAHA API não configurada."

        # WAHA v2/v3 usa GET /api/sessions/{session}
        url = f"{cfg['api_url']}/api/sessions/{cfg['session_name']}"
        
        try:
            response = requests.get(url, headers=WahaAPI.get_headers(), timeout=10)
            if response.status_code == 200:
                data = response.json()
                # Mapeamento de WAHA para o formato que o frontend espera
                # WAHA States: STOPPED, STARTING, SCAN_QR_CODE, WORKING, FAILED
                state = data.get('status', 'STOPPED')
                
                # Mapear para compatibilidade com o JS do Evolution:
                # Evolution states: open, close, connecting, not_found
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
        except Exception as e:
            return False, str(e)

    @staticmethod
    def create_instance():
        """Inicia uma sessão na WAHA"""
        cfg = WahaAPI.get_settings()
        if not WahaAPI.is_configured():
            return False, "WAHA API não configurada."
            
        url = f"{cfg['api_url']}/api/sessions"
        payload = {
            "name": cfg['session_name'],
            "start": True,
            "config": {
                "proxy": None,
                "webhooks": []
            }
        }
        
        try:
            response = requests.post(url, headers=WahaAPI.get_headers(), json=payload, timeout=20)
            if response.status_code in [200, 201]:
                return True, response.json()
            else:
                # Se já existir, a WAHA pode dar erro ou ignorar. 
                # Se der 409 (Conflict), tentamos apenas dar start
                return False, response.text
        except Exception as e:
            return False, str(e)

    @staticmethod
    def connect_instance():
        """Obtém o QR Code da WAHA"""
        cfg = WahaAPI.get_settings()
        # WAHA retorna o QR code diretamente no endpoint ou como base64
        url = f"{cfg['api_url']}/api/{cfg['session_name']}/auth/qr"
        
        try:
            # Pedindo especificamente JSON se possível, ou capturando a imagem
            params = {"format": "json"} 
            response = requests.get(url, headers=WahaAPI.get_headers(), params=params, timeout=20)
            
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
    def list_sessions():
        """Lista todas as sessões configuradas na WAHA"""
        cfg = WahaAPI.get_settings()
        if not cfg['api_url']:
            return False, "URL da API não configurada."
            
        url = f"{cfg['api_url']}/api/sessions"
        try:
            response = requests.get(url, headers=WahaAPI.get_headers(), timeout=10)
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, response.text
        except Exception as e:
            return False, str(e)

    @staticmethod
    def logout_instance():
        """Para/Deleta a sessão na WAHA"""
        cfg = WahaAPI.get_settings()
        # DELETE /api/sessions/{session} remove a sessão e os dados
        url = f"{cfg['api_url']}/api/sessions/{cfg['session_name']}"
        try:
            response = requests.delete(url, headers=WahaAPI.get_headers(), timeout=10)
            if response.status_code in [200, 201, 204]:
                return True, {"message": "Sessão encerrada"}
            else:
                return False, response.text
        except Exception as e:
            return False, str(e)
