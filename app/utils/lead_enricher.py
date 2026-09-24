"""
Módulo de Qualificação Ativa e Enriquecimento Contínuo de Leads (LeadEnricher).

Responsabilidades:
1. Normalização e Formatação de Alta Precisão para Telefones e WhatsApp (formato brasileiro e internacional).
2. Busca Unificada e Desduplicação de Clientes por Múltiplos Formatos de Telefone.
3. Extração Inteligente de Nome (PushName do WhatsApp e identificação conversacional).
4. Extração Heurística e Contínua de Entidades Cadastrais (Nome, E-mail, Segmento, Empresa, CPF/CNPJ).
5. Preenchimento Seguro e Cumulativo no CRM (sem apagar ou corromper dados preexistentes).
6. Geração do Checklist Dinâmico de Qualificação para o Prompt da IA (Ollama / LLMs).
"""

import re
import logging
from datetime import datetime, timezone
from app import db
from app.models import Client, Setting

logger = logging.getLogger(__name__)

# Expressões regulares para detecção de entidades cadastrais em mensagens
REGEX_EMAIL = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', re.IGNORECASE)
REGEX_CPF = re.compile(r'\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b')
REGEX_CNPJ = re.compile(r'\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b')

# Padrões comuns em português para declaração de nome
PATTERNS_NAME = [
    re.compile(r'(?i)\b(?:meu\s+nome\s+(?:é|e)|me\s+chamo|sou\s+(?:o|a)|aqui\s+(?:é|e)\s+(?:o|a)|pode\s+me\s+chamar\s+de)\s+([A-ZÀ-Úa-zà-ú\s]+?)(?=\s+(?:e\b|que\b|gostaria|preciso|quero|tenho|por\s+favor)|\s*[.,;!?]|\s*$)'),
    re.compile(r'(?i)\b(?:aqui\s+quem\s+fala\s+(?:é|e))\s+([A-ZÀ-Úa-zà-ú\s]+?)(?=\s+(?:e\b|que\b|gostaria|preciso|quero|tenho|por\s+favor)|\s*[.,;!?]|\s*$)'),
]

# Padrões comuns para segmento, nicho ou tipo de negócio
PATTERNS_SEGMENT = [
    re.compile(r'(?i)\b(?:trabalho\s+com|atuo\s+(?:no\s+ramo|na\s+(?:área|area))\s+de|minha\s+empresa\s+(?:é|e)\s+uma?|temos\s+uma?|sou\s+(?:dono|propriet[áa]rio|gerente|diretor|consultor|m[ée]dico|dentista|advogado|corretor)\s+de\s+uma?)\s+([A-ZÀ-Úa-zà-ú0-9\s]{3,45})'),
    re.compile(r'(?i)\b(?:nosso\s+segmento\s+(?:é|e)|somos\s+uma?\s+(?:cl[íi]nica|loja|empresa|ind[úu]stria|ag[êe]ncia|imobili[áa]ria|consultoria))\s*([A-ZÀ-Úa-zà-ú0-9\s]{0,35})'),
]


class LeadEnricher:
    """Gerenciador de enriquecimento de leads e precisão cadastral no CRM."""

    @staticmethod
    def clean_digits(phone_str: str) -> str:
        """Extrai apenas dígitos numéricos de qualquer formato de telefone ou JID do WhatsApp."""
        if not phone_str:
            return ""
        # Remove sufixos como @c.us, @s.whatsapp.net, :1 (multi-device)
        raw = str(phone_str).split('@')[0].split(':')[0]
        return ''.join(filter(str.isdigit, raw))

    @staticmethod
    def format_phone_display(phone_str: str) -> str:
        """
        Formata um telefone brasileiro para o padrão legível visual:
        Ex: 5519998306652 -> (19) 99830-6652
        Ex: 19998306652   -> (19) 99830-6652
        Ex: 1932345678    -> (19) 3234-5678
        Ex: 551988306652  -> (19) 98830-6652 (normaliza celular de 8 dígitos)
        """
        digits = LeadEnricher.clean_digits(phone_str)
        if not digits:
            return ""

        # Remove DDI 55 do Brasil se presente no início para padronização
        if digits.startswith("55") and len(digits) in [12, 13]:
            digits = digits[2:]

        # Se for celular de 8 dígitos antigo (DDD + 8 dígitos = 10 dígitos) e primeiro dígito do número >= 6
        if len(digits) == 10:
            ddd = digits[:2]
            num = digits[2:]
            if num[0] in '6789':
                digits = f"{ddd}9{num}"
            else:
                return f"({ddd}) {num[:4]}-{num[4:]}"

        # Celular padrão brasileiro de 11 dígitos (DDD + 9 dígitos)
        if len(digits) == 11:
            ddd = digits[:2]
            num = digits[2:]
            return f"({ddd}) {num[:5]}-{num[5:]}"

        # Fixo padrão brasileiro de 10 dígitos
        if len(digits) == 10:
            ddd = digits[:2]
            num = digits[2:]
            return f"({ddd}) {num[:4]}-{num[4:]}"

        # Fallback para números internacionais ou fora de padrão
        return digits

    @staticmethod
    def find_client_by_phone(phone_str: str) -> Client | None:
        """
        Localiza o cliente no banco com máxima precisão e resiliência:
        - Tenta busca exata;
        - Tenta pelo formato padronizado format_phone_display;
        - Tenta pelos dígitos limpos;
        - Tenta pelos 8 ou 9 dígitos mais significativos + DDD.
        Garante que clientes já cadastrados (por importação, planilha ou manual)
        sejam encontrados imediatamente sem duplicidade.
        """
        digits = LeadEnricher.clean_digits(phone_str)
        if not digits or len(digits) < 8:
            return None

        formatted = LeadEnricher.format_phone_display(digits)

        # 1. Busca por igualdade exata (formatado ou dígitos limpos)
        client = Client.query.filter(
            (Client.phone == formatted) | (Client.phone == digits) | (Client.phone == phone_str)
        ).first()
        if client:
            return client

        # 2. Busca por sufixo de 9 dígitos (DDD + 9 ou apenas número do celular)
        if len(digits) >= 9:
            suffix_9 = digits[-9:]
            client = Client.query.filter(Client.phone.contains(suffix_9)).first()
            if client:
                return client

        # 3. Busca por sufixo dos 8 últimos dígitos (identificador base)
        if len(digits) >= 8:
            suffix_8 = digits[-8:]
            candidates = Client.query.filter(Client.phone.contains(suffix_8)).all()
            if len(candidates) == 1:
                return candidates[0]
            elif len(candidates) > 1:
                # Desempata pelo DDD se possível
                ddd = digits[-11:-9] if len(digits) >= 11 else digits[-10:-8]
                for cand in candidates:
                    cand_clean = LeadEnricher.clean_digits(cand.phone)
                    if ddd in cand_clean:
                        return cand
                return candidates[0]

        return None

    @staticmethod
    def extract_clean_push_name(raw_name: str | None) -> str | None:
        """
        Higieniza e valida o PushName / Nome de perfil do WhatsApp.
        Rejeita strings vazias, números puros, emojis isolados e pontuações.
        Retorna um nome limpo e apresentável ou None.
        """
        if not raw_name or not isinstance(raw_name, str):
            return None

        name = raw_name.strip()
        # Remove caracteres de controle e quebras de linha
        name = re.sub(r'[\r\n\t]+', ' ', name).strip()

        # Remove emojis (Unicode surrogate pairs e blocos emoji)
        name = re.sub(r'[\U00010000-\U0010ffff]', '', name)

        # Remove sufixos profissionais/decorativos comuns no WhatsApp (ex: "Carlos | Vendas", "Ana - Terapeuta")
        name = re.split(r'[\s]*[|•~—\-](\s|$)', name)[0].strip()

        # Remove caracteres gráficos não alfanuméricos exceto espaços, pontos, vírgulas, apóstrofes e hífens
        name = re.sub(r'[^\w\s\.\,\'\-]', '', name)
        name = re.sub(r'\s+', ' ', name).strip()

        # Se virou número ou algo muito curto
        digits_only = ''.join(filter(str.isdigit, name))
        letters_only = ''.join(c for c in name if c.isalpha())

        if len(letters_only) < 2:
            return None

        # Se tiver mais dígitos do que letras (ex: número de telefone como nome)
        if len(digits_only) > len(letters_only):
            return None

        # Limita tamanho razoável para nome
        if len(name) > 60:
            name = name[:60].strip()

        return name if len(name) >= 2 else None

    @staticmethod
    def extract_entities_from_text(text: str, last_assistant_message: str = None) -> dict:
        """
        Extrai entidades cadastrais de forma heurística e contextual a partir do texto do cliente:
        - Nome declarado
        - E-mail
        - CPF ou CNPJ
        - Segmento / Área de Atuação
        """
        entities = {}
        if not text:
            return entities

        clean_text = text.strip()

        # 1. Extração de E-mail
        email_match = REGEX_EMAIL.search(clean_text)
        if email_match:
            entities['email'] = email_match.group(0).lower().strip()

        # 2. Extração de CPF ou CNPJ
        cnpj_match = REGEX_CNPJ.search(clean_text)
        if cnpj_match:
            entities['cpf'] = cnpj_match.group(0).strip()
        else:
            cpf_match = REGEX_CPF.search(clean_text)
            if cpf_match:
                entities['cpf'] = cpf_match.group(0).strip()

        # 3. Extração de Nome
        # 3.1 Padrões explícitos ("meu nome é...", "sou o...", "aqui é a...")
        for pattern in PATTERNS_NAME:
            m = pattern.search(clean_text)
            if m:
                candidate = m.group(1).strip()
                # Remove pontuações finais
                candidate = re.sub(r'[.,;!]+$', '', candidate).strip()
                candidate_words = candidate.split()
                if 1 <= len(candidate_words) <= 5 and all(len(w) >= 2 for w in candidate_words):
                    entities['name'] = " ".join(w.capitalize() for w in candidate_words)
                    break

        # 3.2 Resposta direta quando o bot perguntou o nome no turno imediatamente anterior
        if 'name' not in entities and last_assistant_message:
            last_lower = last_assistant_message.lower()
            name_asked_triggers = [
                'como posso te chamar', 'seu nome', 'com quem falo',
                'com quem tenho o prazer', 'qual o seu nome', 'qual é o seu nome',
                'qual e o seu nome', 'me diga seu nome', 'me informe seu nome'
            ]
            if any(t in last_lower for t in name_asked_triggers):
                words = clean_text.split()
                # Se respondeu com 1 a 4 palavras puramente alfabéticas (sem e-mail, sem URLs)
                if 1 <= len(words) <= 4 and all(w.isalpha() for w in words):
                    # Evita palavras comuns de negação ou dúvidas
                    stop_words = {'não', 'nao', 'sim', 'ok', 'ola', 'olá', 'bom', 'dia', 'tarde', 'noite', 'oi', 'por', 'favor', 'como'}
                    filtered = [w for w in words if w.lower() not in stop_words]
                    if filtered:
                        entities['name'] = " ".join(w.capitalize() for w in filtered)

        # 4. Extração de Segmento / Nicho / Empresa
        for pattern in PATTERNS_SEGMENT:
            m = pattern.search(clean_text)
            if m:
                candidate_seg = m.group(1).strip()
                candidate_seg = re.sub(r'[.,;!]+$', '', candidate_seg).strip()
                if 3 <= len(candidate_seg) <= 45:
                    entities['segment'] = candidate_seg.capitalize()
                    break

        return entities

    @staticmethod
    def enrich_client_record(client: Client, new_data: dict, source_message: str = None) -> bool:
        """
        Aplica os dados extraídos no cadastro do cliente de forma CUMULATIVA e SEGURA:
        - NUNCA apaga dados já preenchidos;
        - Atualiza o nome se o anterior for provisório ("Lead WA...");
        - Preenche e-mail, CPF, segmento se estiverem vazios;
        - Anota novas informações em notes sem apagar histórico;
        - Salva as alterações no banco com commit transacional.
        Retorna True se houve atualização cadastral efetiva.
        """
        if not client or not new_data:
            return False

        updated = False

        # 1. Atualização do Nome
        new_name = new_data.get('name')
        if new_name and isinstance(new_name, str):
            clean_new_name = new_name.strip()
            # Substitui se o atual for genérico, ou se o novo for mais completo
            is_generic = not client.name or client.name.startswith("Lead WA") or client.name.startswith("Contato ")
            if is_generic and len(clean_new_name) >= 2:
                logger.info(f"[LeadEnricher] Atualizando nome de '{client.name}' para '{clean_new_name}' (ID={client.id})")
                client.name = clean_new_name
                updated = True
            elif not is_generic and len(clean_new_name.split()) > len((client.name or "").split()):
                # Novo nome possui sobrenome enquanto o anterior tinha apenas primeiro nome
                if clean_new_name.lower().startswith((client.name or "").lower()):
                    logger.info(f"[LeadEnricher] Complementando nome de '{client.name}' para '{clean_new_name}' (ID={client.id})")
                    client.name = clean_new_name
                    updated = True

        # 2. Atualização de E-mail
        new_email = new_data.get('email')
        if new_email and not client.email:
            logger.info(f"[LeadEnricher] Preenchendo e-mail '{new_email}' para cliente ID={client.id}")
            client.email = new_email.strip().lower()
            updated = True

        # 3. Atualização de CPF / CNPJ
        new_cpf = new_data.get('cpf')
        if new_cpf and not client.cpf:
            logger.info(f"[LeadEnricher] Preenchendo documento '{new_cpf}' para cliente ID={client.id}")
            client.cpf = new_cpf.strip()
            updated = True

        # 4. Atualização de Segmento / Empresa
        new_segment = new_data.get('segment') or new_data.get('company')
        if new_segment and not client.segment:
            logger.info(f"[LeadEnricher] Preenchendo segmento '{new_segment}' para cliente ID={client.id}")
            client.segment = new_segment.strip()
            updated = True

        # 5. Registro cumulativo de notas contextuais
        collected_summary = []
        if new_data.get('email') and new_data.get('email') == client.email:
            collected_summary.append(f"E-mail: {client.email}")
        if new_data.get('segment') and new_data.get('segment') == client.segment:
            collected_summary.append(f"Segmento: {client.segment}")
        if new_data.get('cpf') and new_data.get('cpf') == client.cpf:
            collected_summary.append(f"Doc: {client.cpf}")
        if new_data.get('name') and new_data.get('name') == client.name:
            collected_summary.append(f"Nome: {client.name}")

        new_note = new_data.get('notes') or new_data.get('interest')
        if not new_note and collected_summary:
            new_note = ", ".join(collected_summary)

        if new_note and isinstance(new_note, str) and len(new_note.strip()) >= 3:
            timestamp_str = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")
            entry = f"[{timestamp_str}] Bot Coletou: {new_note.strip()}"
            if client.notes:
                # Evita duplicar anotação exatamente igual
                if entry not in client.notes and new_note.strip() not in client.notes:
                    client.notes = f"{client.notes}\n{entry}"
                    updated = True
            else:
                client.notes = entry
                updated = True

        # Se o lead estava como 'lead' e forneceu nome real e e-mail/interesse, qualifica para 'contato'
        if client.status == 'lead' and client.name and not client.name.startswith("Lead WA") and (client.email or client.segment):
            logger.info(f"[LeadEnricher] Qualificando lead ID={client.id} para status 'contato'")
            client.status = 'contato'
            updated = True

        if updated:
            try:
                client.updated_at = datetime.now(timezone.utc)
                db.session.commit()
                logger.info(f"[LeadEnricher] Cadastro do cliente ID={client.id} atualizado com sucesso no CRM.")
            except Exception as e:
                db.session.rollback()
                logger.error(f"[LeadEnricher] Erro ao persistir atualização do cliente ID={client.id}: {e}", exc_info=True)
                return False

        return updated

    @staticmethod
    def build_qualification_prompt_context(client: Client) -> str:
        """
        Gera o checklist contextual dinâmico para inserção no System Prompt do LLM.
        Informa com clareza quais dados já foram coletados e quais devem ser
        perguntados de forma natural e consultiva durante a interação.
        """
        if not client:
            return ""

        has_real_name = bool(client.name and not client.name.startswith("Lead WA") and not client.name.startswith("Contato "))
        has_phone = bool(client.phone)
        has_email = bool(client.email)
        has_segment = bool(client.segment)

        lines = [
            "--- FICHA CADASTRAL DO CLIENTE NO CRM (QUALIFICAÇÃO EM ANDAMENTO) ---",
            f"- Nome: {client.name if has_real_name else '[PENDENTE - Pergunte como pode chamar o contato]'}",
            f"- WhatsApp: {client.phone if has_phone else '[CONFIRMADO PELA CONEXÃO]'}",
            f"- E-mail: {client.email if has_email else '[PENDENTE - Solicite o e-mail de contato]'}",
            f"- Segmento / Empresa: {client.segment if has_segment else '[PENDENTE - Pergunte sobre a empresa ou área de atuação]'}",
            f"- Status no Funil: {client.status.upper() if client.status else 'LEAD'}",
        ]

        # Priorização de qual pergunta fazer a seguir
        missing = []
        if not has_real_name:
            missing.append("Nome do cliente (Como podemos chamá-lo)")
        if not has_segment:
            missing.append("Segmento / Ramo de negócio ou empresa")
        if not has_email:
            missing.append("E-mail para envio de propostas ou informações")

        if missing:
            next_target = missing[0]
            lines.append("\n--- DIRETRIZ DE COLETA ATIVA DE DADOS (CONSULTIVA E NATURAL) ---")
            lines.append("Seu papel como consultor comercial inclui preencher o cadastro deste lead:")
            lines.append(f"1. Responda primeiro à dúvida ou necessidade imediata trazida pelo cliente;")
            lines.append(f"2. Após responder, finalize com UMA pergunta natural e simpática para coletar: {next_target};")
            lines.append("3. NUNCA faça mais de uma pergunta de cadastro na mesma mensagem e NUNCA pareça um formulário rígido.")
        else:
            lines.append("\n--- CADASTRO DO LEAD COMPLETO NO CRM ---")
            lines.append("Todos os dados principais foram coletados. Foque em avançar a negociação ou agendar atendimento especializado.")

        return "\n".join(lines)
