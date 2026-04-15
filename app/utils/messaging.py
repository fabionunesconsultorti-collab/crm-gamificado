import re
from datetime import datetime

class WhatsAppEngine:
    @staticmethod
    def interpolate(text, client, user=None):
        if not text:
            return ""

        # Dicionário base de variáveis
        mapping = {
            "[NOME]": client.name.split()[0] if client.name else "Cliente",
            "[NOME_COMPLETO]": client.name or "Cliente",
            "[DATA]": datetime.today().strftime('%d/%m/%Y'),
            "[HORA]": datetime.now().strftime('%H:%M'),
            "[STATUS]": client.status.upper() if client.status else "",
            "[VENDEDOR]": user.username if user else (client.assigned_to.username if getattr(client, 'assigned_to', None) else "Nossa Equipe"),
        }

        # Substituição via Regex para ignorar caixa (ex: [nome] ou [NOME])
        for key, value in mapping.items():
            pattern = re.compile(re.escape(key), re.IGNORECASE)
            text = pattern.sub(str(value), text)

        return text
