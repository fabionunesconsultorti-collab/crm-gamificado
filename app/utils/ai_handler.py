from google import genai
from app.models import Setting
import requests

class AIHandler:
    @staticmethod
    def get_config():
        settings_raw = Setting.query.all()
        config = {s.key: s.value for s in settings_raw}
        return {
            'api_key': config.get('ai_api_key', ''),
            'provider': config.get('ai_provider', 'google'),
            'prompt': config.get('ai_system_prompt', 
                "Você é um assistente de vendas pacífico, amigável e vendedor. "
                "Reescreva a mensagem a seguir de forma natural e ligeiramente diferente, mantendo o sentido original. "
                "IMPORTANTE: Não altere nem remova as palavras dentro de colchetes, como [NOME], [DATA], [STATUS], etc."
            )
        }

    @staticmethod
    def rewrite_message(text):
        cfg = AIHandler.get_config()
        if not cfg['api_key']:
            return text, "API Key de IA não configurada."

        try:
            full_prompt = f"{cfg['prompt']}\n\nMensagem original: {text}\n\nRetorne apenas a nova mensagem reescrita:"
            
            if cfg['provider'] == 'deepseek':
                headers = {
                    "Authorization": f"Bearer {cfg['api_key']}",
                    "Content-Type": "application/json"
                }
                data = {
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": cfg['prompt']},
                        {"role": "user", "content": f"Mensagem original: {text}\n\nRetorne apenas a nova mensagem reescrita:"}
                    ],
                    "stream": False
                }
                
                resp = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=data, timeout=30)
                
                if resp.status_code == 200:
                    resp_json = resp.json()
                    choices = resp_json.get("choices", [])
                    if choices and choices[0].get("message"):
                        return choices[0]["message"]["content"].strip(), None
                    else:
                        return text, "Resposta da IA vazia (DeepSeek)."
                else:
                    error_data = resp.json() if resp.text else {}
                    err_msg = error_data.get('error', {}).get('message', resp.text)
                    return text, f"Erro DeepSeek ({resp.status_code}): {err_msg}"
                    
            else:
                # Default: Google Gemini
                client = genai.Client(api_key=cfg['api_key'])
                response = client.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=full_prompt
                )

                if response and response.text:
                    return text.strip() if response.text.strip() == "" else response.text.strip(), None
                else:
                    return text, "Resposta da IA vazia."
                    
        except Exception as e:
            error_msg = str(e)
            print(f"Erro na IA: {error_msg}")
            
            if cfg['provider'] == 'google':
                if "PERMISSION_DENIED" in error_msg:
                    user_msg = "Sua API Key foi negada. O projeto no Google Cloud pode estar suspenso ou sem permissão."
                elif "RESOURCE_EXHAUSTED" in error_msg or "limit: 0" in error_msg:
                    user_msg = "Limite de cota excedido (ou bloqueado na sua região sem faturamento ativado). Verifique seu faturamento no Google AI Studio."
                elif "API_KEY_INVALID" in error_msg:
                    user_msg = "A chave de API informada é inválida."
                else:
                    user_msg = f"Erro na IA: {error_msg[:100]}..."
            else:
                user_msg = f"Erro de Conexão na IA ({cfg['provider']}): {error_msg[:100]}..."
                
            return text, user_msg

    @staticmethod
    def generate_reply(customer_message):
        cfg = AIHandler.get_config()
        if not cfg['api_key']:
            return "Desculpe, a IA ainda não está configurada neste momento.", "API Key não configurada."
            
        system_prompt = "Você é um assistente de vendas educado e prestativo. Responda de forma curta e amigável ao cliente."
        full_prompt = f"{system_prompt}\n\nCliente diz: {customer_message}\n\nResponda:"
        
        try:
            if cfg['provider'] == 'deepseek':
                headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}
                data = {
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": customer_message}
                    ],
                    "stream": False
                }
                resp = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=data, timeout=30)
                if resp.status_code == 200:
                    resp_json = resp.json()
                    choices = resp_json.get("choices", [])
                    if choices and choices[0].get("message"):
                        return choices[0]["message"]["content"].strip(), None
                return "Tivemos um pequeno erro de comunicação interna.", f"DeepSeek Status: {resp.status_code}"
            else:
                # Gemini
                client = genai.Client(api_key=cfg['api_key'])
                response = client.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=full_prompt
                )
                if response and response.text:
                    return response.text.strip(), None
                return "Tivemos um erro ao gerar a resposta.", "Resposta vazia do Gemini"
        except Exception as e:
            print(f"Erro no generate_reply: {e}")
            return "No momento não consigo processar sua mensagem.", str(e)

