import os
import re
import requests
from google import genai
from app.models import Setting

class AIHandler:
    @staticmethod
    def clean_text(text):
        """Remove tags de raciocínio como <think>...</think> e aspas extras envolventes."""
        if not text:
            return ""
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        # Remove aspas externas se o modelo retornou a frase inteira entre aspas
        if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
            text = text[1:-1].strip()
        return text

    @staticmethod
    def is_refusal(text):
        """Detecta se o modelo retornou uma recusa de execução ou censura indevida."""
        if not text:
            return False
        lower = text.lower().strip()
        refusal_patterns = [
            r"desculpe,?\s*(mas)?\s*n[aã]o posso",
            r"n[aã]o posso cumprir",
            r"n[aã]o posso fornecer",
            r"n[aã]o posso atender",
            r"n[aã]o posso ajudar",
            r"n[aã]o posso reescrever",
            r"n[aã]o posso colaborar",
            r"sinto muito,?\s*(mas)?\s*n[aã]o posso",
            r"como um modelo de linguagem",
            r"como uma intelig[eê]ncia artificial",
            r"como um modelo de ia",
            r"i cannot fulfill",
            r"i am unable to",
            r"i cannot help",
            r"i'm sorry,?\s*(but)?\s*i cannot",
            r"as an ai"
        ]
        for pat in refusal_patterns:
            if re.search(pat, lower):
                return True
        return False

    @staticmethod
    def get_config():
        settings_raw = Setting.query.all()
        config = {s.key: s.value for s in settings_raw}
        return {
            'api_key': config.get('ai_api_key', ''),
            'provider': config.get('ai_provider', 'ollama'),
            'prompt': config.get('ai_system_prompt', 
                "Você é um assistente de redação e comunicação corporativa. "
                "Sua função é reescrever comunicados, mensagens de atendimento, notificações e mensagens operacionais de empresas para clientes, "
                "tornando o texto claro, profissional e variado, sem alterar o sentido nem o objetivo do comunicado original. "
                "IMPORTANTE: "
                "1. Mantenha intactos marcadores e variáveis entre colchetes como [NOME], [DATA], [STATUS], [HORA], [VENDEDOR]. "
                "2. Mantenha links e números de telefone exatamente iguais. "
                "3. Retorne estritamente o texto reescrito pronto para envio, sem explicações, introduções ou aspas."
            ),
            'ollama_url': (config.get('ai_ollama_url') or os.environ.get('OLLAMA_URL', 'http://localhost:11434')).rstrip('/'),
            'ollama_model': config.get('ai_ollama_model', 'qwen2.5:1.5b')
        }

    @staticmethod
    def rewrite_message(text):
        """Reescreve uma mensagem de template ou campanha para torná-la única e humanizada."""
        cfg = AIHandler.get_config()

        # Validações por provedor
        if cfg['provider'] != 'ollama' and not cfg['api_key']:
            return text, "API Key de IA não configurada nas opções administrativas."

        try:
            user_instruction = (
                f"Reescreva e parafraseie o seguinte comunicado corporativo mantendo o mesmo significado e sem alterar variáveis entre colchetes:\n\n{text}"
            )
            full_prompt = f"{cfg['prompt']}\n\n{user_instruction}\n\nTexto reescrito:"

            # Provedor 1: OLLAMA (Local Docker)
            if cfg['provider'] == 'ollama':
                url = f"{cfg['ollama_url']}/api/chat"
                payload = {
                    "model": cfg['ollama_model'],
                    "messages": [
                        {"role": "system", "content": cfg['prompt']},
                        {"role": "user", "content": user_instruction}
                    ],
                    "stream": False,
                    "options": {"temperature": 0.7}
                }
                resp = requests.post(url, json=payload, timeout=60)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("message", {}).get("content", "")
                    cleaned = AIHandler.clean_text(content)
                    if AIHandler.is_refusal(cleaned):
                        return text, f"Aviso de IA: O modelo recusou o texto ('{cleaned[:60]}...'). Mensagem original mantida por segurança."
                    return (cleaned if cleaned else text), None
                elif resp.status_code == 404:
                    return text, f"Modelo '{cfg['ollama_model']}' não encontrado no Ollama. Execute 'docker exec -it crm-ollama ollama pull {cfg['ollama_model']}'."
                else:
                    return text, f"Erro no Ollama ({resp.status_code}): {resp.text}"

            # Provedor 2: DEEPSEEK (Cloud API)
            elif cfg['provider'] == 'deepseek':
                headers = {
                    "Authorization": f"Bearer {cfg['api_key']}",
                    "Content-Type": "application/json"
                }
                data = {
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": cfg['prompt']},
                        {"role": "user", "content": user_instruction}
                    ],
                    "stream": False
                }
                resp = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=data, timeout=30)
                if resp.status_code == 200:
                    choices = resp.json().get("choices", [])
                    if choices and choices[0].get("message"):
                        cleaned = AIHandler.clean_text(choices[0]["message"]["content"])
                        if AIHandler.is_refusal(cleaned):
                            return text, f"Aviso de IA: O modelo recusou o texto ('{cleaned[:60]}...'). Mensagem original mantida por segurança."
                        return (cleaned if cleaned else text), None
                    return text, "Resposta da IA vazia (DeepSeek)."
                else:
                    error_data = resp.json() if resp.text else {}
                    err_msg = error_data.get('error', {}).get('message', resp.text)
                    return text, f"Erro DeepSeek ({resp.status_code}): {err_msg}"

            # Provedor 3: GOOGLE GEMINI (Cloud API)
            else:
                client = genai.Client(api_key=cfg['api_key'])
                response = client.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=full_prompt
                )
                if response and response.text:
                    cleaned = AIHandler.clean_text(response.text)
                    if AIHandler.is_refusal(cleaned):
                        return text, f"Aviso de IA: O modelo recusou o texto ('{cleaned[:60]}...'). Mensagem original mantida por segurança."
                    return (cleaned if cleaned else text), None
                return text, "Resposta da IA vazia."

        except requests.exceptions.ConnectionError:
            if cfg['provider'] == 'ollama':
                return text, f"Não foi possível conectar ao Ollama em {cfg['ollama_url']}. Verifique se o container está rodando."
            return text, "Erro de conexão de rede com a API de IA."
        except Exception as e:
            error_msg = str(e)
            print(f"Erro na IA (rewrite): {error_msg}")
            return text, f"Erro na IA ({cfg['provider']}): {error_msg[:100]}"

    @staticmethod
    def generate_chat_reply(customer_message, chat_history=None, client_info=None):
        """
        Gera respostas inteligentes e contextualizadas para o WhatsApp utilizando histórico
        conversacional (multi-turno) e dados cadastrais do cliente no CRM.
        """
        cfg = AIHandler.get_config()
        if cfg['provider'] != 'ollama' and not cfg['api_key']:
            return "Olá! Recebemos sua mensagem e entraremos em contato em breve.", "API Key não configurada."

        base_prompt = (
            "Você é um assistente de atendimento educado, atencioso e prestativo de uma empresa comercial no WhatsApp. "
            "Responda de forma clara, natural, profissional e amigável em português do Brasil. "
            "Mantenha respostas concisas e legíveis em tela de celular (evite blocos excessivamente longos). "
            "Busque sempre sanar as dúvidas do cliente ou indicar que um consultor da equipe entrará em contato quando necessário."
        )

        # Enriquecimento com dados do CRM se disponíveis
        context_lines = []
        if client_info and isinstance(client_info, dict):
            if client_info.get('name'):
                context_lines.append(f"Nome do cliente: {client_info['name']}")
            if client_info.get('status'):
                context_lines.append(f"Etapa no CRM: {client_info['status']}")
            if client_info.get('segment'):
                context_lines.append(f"Segmento de mercado: {client_info['segment']}")
            if client_info.get('assigned_user'):
                context_lines.append(f"Consultor responsável: {client_info['assigned_user']}")

        if context_lines:
            system_prompt = (
                f"{base_prompt}\n\nContexto do contato no CRM:\n"
                + "\n".join(f"- {line}" for line in context_lines)
                + "\nUse essas informações para personalizar o atendimento com empatia e naturalidade."
            )
        else:
            system_prompt = base_prompt

        # Construção da lista estruturada de mensagens (Chat Multi-turno)
        messages = [{"role": "system", "content": system_prompt}]
        if chat_history and isinstance(chat_history, list):
            for turn in chat_history:
                if isinstance(turn, dict) and turn.get('role') in ['user', 'assistant'] and turn.get('content'):
                    messages.append({"role": turn['role'], "content": str(turn['content']).strip()})

        # Adiciona a mensagem unificada atual do cliente
        messages.append({"role": "user", "content": customer_message.strip()})

        try:
            # Provedor 1: OLLAMA (Local Docker)
            if cfg['provider'] == 'ollama':
                url = f"{cfg['ollama_url']}/api/chat"
                payload = {
                    "model": cfg['ollama_model'],
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "num_predict": 160
                    }
                }
                resp = requests.post(url, json=payload, timeout=60)
                if resp.status_code == 200:
                    content = resp.json().get("message", {}).get("content", "")
                    cleaned = AIHandler.clean_text(content)
                    if cleaned and not AIHandler.is_refusal(cleaned):
                        return cleaned, None
                return "Olá! Recebemos sua mensagem e já vamos te responder.", f"Ollama retorno vazio ou recusa ({resp.status_code})"

            # Provedor 2: DEEPSEEK (Cloud API)
            elif cfg['provider'] == 'deepseek':
                headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}
                data = {
                    "model": "deepseek-chat",
                    "messages": messages,
                    "stream": False
                }
                resp = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=data, timeout=35)
                if resp.status_code == 200:
                    choices = resp.json().get("choices", [])
                    if choices and choices[0].get("message"):
                        cleaned = AIHandler.clean_text(choices[0]["message"]["content"])
                        if cleaned and not AIHandler.is_refusal(cleaned):
                            return cleaned, None
                return "Olá! Recebemos sua mensagem.", f"DeepSeek Status: {resp.status_code}"

            # Provedor 3: GOOGLE GEMINI (Cloud API)
            else:
                client = genai.Client(api_key=cfg['api_key'])
                # Formata o histórico conversacional como texto concatenado para o Gemini
                conversation_text = ""
                for msg in messages:
                    if msg['role'] == 'system':
                        continue
                    prefix = "Cliente" if msg['role'] == 'user' else "Assistente"
                    conversation_text += f"{prefix}: {msg['content']}\n"

                full_prompt = f"{system_prompt}\n\nHistórico da conversa:\n{conversation_text}\nAssistente:"
                response = client.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=full_prompt
                )
                if response and response.text:
                    cleaned = AIHandler.clean_text(response.text)
                    if cleaned and not AIHandler.is_refusal(cleaned):
                        return cleaned, None
                return "Olá! Recebemos sua mensagem.", "Resposta vazia ou recusada pelo Gemini"

        except Exception as e:
            print(f"Erro no generate_chat_reply: {e}")
            return "Olá! Recebemos sua mensagem e um de nossos atendentes entrará em contato em instantes.", str(e)

    @staticmethod
    def generate_reply(customer_message):
        """Wrapper de compatibilidade para chamadas legadas de resposta simples."""
        return AIHandler.generate_chat_reply(customer_message)


    @staticmethod
    def generate_text(instruction):
        """Gera novos textos de vendas, templates promocionais e mensagens do zero a partir de uma instrução."""
        cfg = AIHandler.get_config()
        if cfg['provider'] != 'ollama' and not cfg['api_key']:
            return None, "API Key de IA não configurada nas opções administrativas."

        system_prompt = (
            "Você é um copywriter sênior especializado em vendas e relacionamento por WhatsApp. "
            "Crie mensagens altamente persuasivas, humanas, dinâmicas e prontas para envio comercial. "
            "Sempre que fizer sentido, utilize variáveis entre colchetes como [NOME], [DATA], [HORA], [STATUS], [VENDEDOR]. "
            "IMPORTANTE: Retorne APENAS o texto da mensagem final sugerida, sem introduções como 'Aqui está sua mensagem:' ou explicações."
        )

        try:
            # Provedor 1: OLLAMA (Local Docker)
            if cfg['provider'] == 'ollama':
                url = f"{cfg['ollama_url']}/api/chat"
                payload = {
                    "model": cfg['ollama_model'],
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Crie uma mensagem de WhatsApp para o seguinte objetivo: {instruction}"}
                    ],
                    "stream": False,
                    "options": {"temperature": 0.7}
                }
                resp = requests.post(url, json=payload, timeout=90)
                if resp.status_code == 200:
                    content = resp.json().get("message", {}).get("content", "")
                    cleaned = AIHandler.clean_text(content)
                    if cleaned:
                        if AIHandler.is_refusal(cleaned):
                            return None, f"A IA recusou a instrução ('{cleaned[:60]}...'). Tente reformular o objetivo da mensagem."
                        return cleaned, None
                elif resp.status_code == 404:
                    return None, f"Modelo '{cfg['ollama_model']}' não encontrado no Ollama. Execute 'docker exec -it crm-ollama-1 ollama pull {cfg['ollama_model']}' ou selecione outro modelo em Configurações."
                return None, f"Erro ao gerar com Ollama: {resp.text}"

            # Provedor 2: DEEPSEEK
            elif cfg['provider'] == 'deepseek':
                headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}
                data = {
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": instruction}
                    ],
                    "stream": False
                }
                resp = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=data, timeout=40)
                if resp.status_code == 200:
                    choices = resp.json().get("choices", [])
                    if choices and choices[0].get("message"):
                        cleaned = AIHandler.clean_text(choices[0]["message"]["content"])
                        if AIHandler.is_refusal(cleaned):
                            return None, f"A IA recusou a instrução ('{cleaned[:60]}...'). Tente reformular o objetivo da mensagem."
                        return cleaned, None
                return None, f"Erro DeepSeek: {resp.text}"

            # Provedor 3: GEMINI
            else:
                client = genai.Client(api_key=cfg['api_key'])
                full_prompt = f"{system_prompt}\n\nInstrução: {instruction}\n\nTexto gerado:"
                response = client.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=full_prompt
                )
                if response and response.text:
                    cleaned = AIHandler.clean_text(response.text)
                    if AIHandler.is_refusal(cleaned):
                        return None, f"A IA recusou a instrução ('{cleaned[:60]}...'). Tente reformular o objetivo da mensagem."
                    return cleaned, None
                return None, "Resposta vazia da IA."

        except Exception as e:
            print(f"Erro no generate_text: {e}")
            return None, str(e)

    @staticmethod
    def get_available_models(ollama_url=None):
        """Consulta o servidor Ollama para listar os modelos locais já baixados."""
        cfg = AIHandler.get_config()
        url = (ollama_url or cfg['ollama_url']).rstrip('/')
        try:
            resp = requests.get(f"{url}/api/tags", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                return {"online": True, "models": models, "url": url}
            return {"online": False, "models": [], "error": f"Status HTTP {resp.status_code}", "url": url}
        except Exception as e:
            return {"online": False, "models": [], "error": str(e), "url": url}


