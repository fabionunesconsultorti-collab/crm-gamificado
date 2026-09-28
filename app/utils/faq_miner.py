import json
import logging
import re
from datetime import datetime, timedelta, timezone
from sqlalchemy import desc
from app import db
from app.models import MessageLog, KnowledgeDoc, Setting
from app.utils.ai_handler import AIHandler
from app.utils.rag_engine import RAGEngine

logger = logging.getLogger(__name__)

class FAQMiner:
    """
    Minerador e Sintetizador Autônomo de Perguntas e Respostas Frequentes (FAQ)
    a partir de conversas reais de WhatsApp registradas no CRM.
    """

    TRIVIAL_PATTERNS = {
        'oi', 'ola', 'olá', 'bom dia', 'boa tarde', 'boa noite',
        'ok', 'ta bom', 'tá bom', 'obrigado', 'obrigada', 'valeu',
        'sim', 'nao', 'não', 'blz', 'beleza', 'opa', 'alo', 'alô'
    }

    @classmethod
    def is_substantive_message(cls, text: str) -> bool:
        """Verifica se a mensagem do lead tem conteúdo substantivo e não é apenas saudação rápida."""
        if not text:
            return False
        clean = re.sub(r'[^\w\s]', '', text.lower()).strip()
        if len(clean) < 6:
            return False
        if clean in cls.TRIVIAL_PATTERNS:
            return False
        return True

    @classmethod
    def collect_recent_dialogues(cls, limit_messages: int = 200, days: int = 30) -> list[dict]:
        """
        Agrupa conversas recentes de entrada e saída por chat_id no banco relacional.
        Retorna pares conversacionais estruturados (Pergunta do Lead -> Resposta Enviada).
        """
        since_date = datetime.now(timezone.utc) - timedelta(days=days)

        logs = MessageLog.query.filter(
            MessageLog.timestamp >= since_date
        ).order_by(
            MessageLog.chat_id,
            MessageLog.timestamp.asc()
        ).limit(limit_messages).all()

        if not logs:
            return []

        conversations = {}
        for log in logs:
            cid = log.chat_id or (f"client_{log.client_id}" if log.client_id else "unknown")
            if cid not in conversations:
                conversations[cid] = []
            
            # Normaliza direção da mensagem
            direction = log.direction or ('inbound' if log.status == 'received' else 'outbound')
            conversations[cid].append({
                "direction": direction,
                "content": (log.content or "").strip(),
                "timestamp": log.timestamp.isoformat() if log.timestamp else ""
            })

        dialogue_pairs = []
        for cid, msgs in conversations.items():
            last_inbound = None
            for msg in msgs:
                if msg['direction'] == 'inbound':
                    if cls.is_substantive_message(msg['content']):
                        last_inbound = msg['content']
                elif msg['direction'] == 'outbound' and last_inbound:
                    reply = msg['content']
                    # Limpa prefixos de lote se existirem
                    clean_reply = re.sub(r'^\[Lote \d+ msgs\]\s*', '', reply).strip()
                    if clean_reply and len(clean_reply) > 10:
                        dialogue_pairs.append({
                            "chat_id": cid,
                            "question": last_inbound,
                            "answer": clean_reply
                        })
                    last_inbound = None

        logger.info(f"[FAQMiner] {len(dialogue_pairs)} pares de diálogo extraídos de {len(conversations)} chats.")
        return dialogue_pairs

    @classmethod
    def synthesize_faqs_with_llm(cls, dialogues: list[dict], max_faqs: int = 5) -> list[dict]:
        """
        Envia os diálogos minerados para o LLM gerar pares canônicos de Pergunta & Resposta.
        """
        if not dialogues:
            return []

        # Amostra até 20 diálogos mais relevantes
        sample = dialogues[:25]
        dialogue_text = ""
        for idx, d in enumerate(sample, 1):
            dialogue_text += f"\n--- Diálogo {idx} ---\nCliente: {d['question']}\nResposta da Empresa: {d['answer']}\n"

        system_prompt = (
            "Você é um Especialista em Engenharia de Conhecimento e RAG para Atendimento ao Cliente. "
            "Sua tarefa é analisar os diálogos reais de WhatsApp fornecidos e identificar as principais DÚVIDAS E PERGUNTAS FREQUENTES. "
            "Para cada dúvida identificada, formule uma Pergunta Canônica clara e uma Resposta Oficial completa, precisa e profissional. "
            "Responda ESTRITAMENTE em formato JSON com uma lista de objetos contendo: "
            "'question' (pergunta clara), 'answer' (resposta oficial consolidada), 'title' (título curto para o documento de FAQ) e 'tags' (lista de palavras-chave). "
            "NÃO inclua saudações triviais. Retorne APENAS o JSON válido sem blocos de texto adicionais."
        )

        user_content = (
            f"Analise os diálogos abaixo e extraia até {max_faqs} perguntas e respostas frequentes consolidadas:\n"
            f"{dialogue_text}\n\n"
            "Retorne a resposta estritamente no formato:\n"
            "[\n  {\"title\": \"FAQ: ...\", \"question\": \"...\", \"answer\": \"...\", \"tags\": [\"...\"]}\n]"
        )

        cfg = AIHandler.get_config()
        raw_output = ""

        try:
            # Prioriza Ollama local
            if cfg['provider'] == 'ollama':
                import requests
                url = f"{cfg['ollama_url']}/api/chat"
                resp = requests.post(url, json={
                    "model": cfg['ollama_model'],
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 800}
                }, timeout=90)
                if resp.status_code == 200:
                    raw_output = resp.json().get("message", {}).get("content", "")
            else:
                raw_output, _ = AIHandler.generate_text(f"{system_prompt}\n\n{user_content}")
        except Exception as e:
            logger.error(f"[FAQMiner] Falha ao invocar LLM para síntese de FAQs: {e}")
            return []

        raw_output = AIHandler.clean_text(raw_output or "")
        json_match = re.search(r'\[\s*\{.*\}\s*\]', raw_output, re.DOTALL)
        if not json_match:
            logger.warning(f"[FAQMiner] Formato JSON não identificado na resposta do LLM: {raw_output[:200]}")
            return []

        try:
            parsed = json.loads(json_match.group(0))
            if isinstance(parsed, list):
                return parsed
        except Exception as e:
            logger.error(f"[FAQMiner] Erro ao parsear JSON de FAQs: {e}")

        return []

    @classmethod
    def save_and_index_faqs(cls, faqs: list[dict], auto_index: bool = True) -> list[KnowledgeDoc]:
        """
        Salva os FAQs minerados como KnowledgeDoc e indexa automaticamente no ChromaDB.
        """
        saved_docs = []
        if not faqs:
            return saved_docs

        for item in faqs:
            title = item.get('title') or f"FAQ: {item.get('question', '')[:60]}"
            question = item.get('question', '').strip()
            answer = item.get('answer', '').strip()
            tags = ", ".join(item.get('tags', [])) if isinstance(item.get('tags'), list) else str(item.get('tags', ''))

            if not question or not answer:
                continue

            content = (
                f"**Pergunta do Cliente:**\n{question}\n\n"
                f"**Resposta Oficial:**\n{answer}\n\n"
                f"**Palavras-Chave:** {tags}"
            )

            # Verifica se já existe um documento com o mesmo título para evitar duplicidade
            existing = KnowledgeDoc.query.filter(
                (KnowledgeDoc.title == title) | (KnowledgeDoc.title == f"FAQ: {question[:60]}")
            ).first()

            if existing:
                existing.content = content
                existing.category = 'faq'
                doc = existing
                logger.info(f"[FAQMiner] Documento FAQ existente atualizado: ID={doc.id} ('{title}')")
            else:
                doc = KnowledgeDoc(
                    title=title,
                    content=content,
                    category='faq'
                )
                db.session.add(doc)
                db.session.flush()
                logger.info(f"[FAQMiner] Novo documento FAQ criado: ID={doc.id} ('{title}')")

            db.session.commit()
            saved_docs.append(doc)

            # Indexação imediata no motor RAG híbrido
            if auto_index:
                try:
                    RAGEngine.index_document(
                        doc_id=doc.id,
                        title=doc.title,
                        content=doc.content,
                        category='faq'
                    )
                except Exception as e:
                    logger.warning(f"[FAQMiner] Erro ao indexar FAQ ID={doc.id} no ChromaDB: {e}")

        return saved_docs

    @classmethod
    def run_mining_cycle(cls, limit_messages: int = 150, days: int = 30) -> dict:
        """
        Executa o ciclo completo de mineração, aprendizado e indexação de FAQs.
        """
        dialogues = cls.collect_recent_dialogues(limit_messages=limit_messages, days=days)
        if not dialogues:
            return {
                "ok": True,
                "message": "Nenhum diálogo substantivo recente encontrado para mineração.",
                "dialogues_analyzed": 0,
                "faqs_generated": 0,
                "faqs": []
            }

        faqs = cls.synthesize_faqs_with_llm(dialogues)
        saved_docs = cls.save_and_index_faqs(faqs, auto_index=True)

        return {
            "ok": True,
            "message": f"Sucesso! {len(saved_docs)} novos FAQs aprendidos e indexados na Base de Conhecimento.",
            "dialogues_analyzed": len(dialogues),
            "faqs_generated": len(saved_docs),
            "faqs": [
                {"id": d.id, "title": d.title, "preview": d.content[:140]}
                for d in saved_docs
            ]
        }
