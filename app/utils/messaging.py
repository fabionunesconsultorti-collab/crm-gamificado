import re
from datetime import datetime

class WhatsAppEngine:
    @staticmethod
    def interpolate(text, client, user=None):
        if not text:
            return ""

        is_dict = isinstance(client, dict)
        
        c_name = client.get('name') if is_dict else getattr(client, 'name', None)
        c_status = client.get('status', '') if is_dict else getattr(client, 'status', '')
        
        assigned_username = "Nossa Equipe"
        if not is_dict and getattr(client, 'assigned_to', None):
             if hasattr(client.assigned_to, 'username'):
                 assigned_username = client.assigned_to.username

        # Dicionário base de variáveis
        mapping = {
            "[NOME]": c_name.split()[0] if c_name else "Cliente",
            "[NOME_COMPLETO]": c_name or "Cliente",
            "[DATA]": datetime.today().strftime('%d/%m/%Y'),
            "[HORA]": datetime.now().strftime('%H:%M'),
            "[STATUS]": c_status.upper() if c_status else "",
            "[VENDEDOR]": user.username if user else assigned_username,
        }

        # Substituição via Regex para ignorar caixa (ex: [nome] ou [NOME])
        for key, value in mapping.items():
            pattern = re.compile(re.escape(key), re.IGNORECASE)
            text = pattern.sub(str(value), text)

        return text
