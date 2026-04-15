import requests
import json
from app.models import Setting

class EvolutionAPI:
    @staticmethod
    def get_settings():
        settings_raw = Setting.query.all()
        config = {s.key: s.value for s in settings_raw}
        return {
            'api_url': config.get('evo_api_url', '').rstrip('/'),
            'api_key': config.get('evo_api_key', ''),
            'instance_name': config.get('evo_instance', '')
        }

    @staticmethod
    def is_configured():
        cfg = EvolutionAPI.get_settings()
        return bool(cfg['api_url'] and cfg['api_key'] and cfg['instance_name'])

    @staticmethod
    def send_text(phone_number, text):
        cfg = EvolutionAPI.get_settings()
        if not EvolutionAPI.is_configured():
            return False, "Evolution API não configurada nas Definições."

        # Format number (remove non-digits)
        clean_phone = ''.join(filter(str.isdigit, str(phone_number)))
        
        # EvolutionAPI Endpoint
        url = f"{cfg['api_url']}/message/sendText/{cfg['instance_name']}"
        
        headers = {
            'Content-Type': 'application/json',
            'apikey': cfg['api_key']
        }
        
        payload = {
            "number": clean_phone,
            "options": {
                "delay": 1200,
                "presence": "composing"
            },
            "textMessage": {
                "text": text
            }
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if response.status_code in [200, 201]:
                return True, response.json()
            else:
                return False, response.text
        except Exception as e:
            return False, str(e)
