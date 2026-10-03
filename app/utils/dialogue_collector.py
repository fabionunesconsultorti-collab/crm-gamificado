"""
Módulo de Captura e Curadoria Contínua de Diálogos WhatsApp (DialogueCollector).

Responsabilidades:
1. Captura e separação precisa entre o que o lead fala e o que o operador humano responde (Waha Capture).
2. Formação automática de pares de diálogo (Gold Standard Pairs: Lead Prompt -> Human Response).
3. Gerenciamento do ciclo de vida de Fine-Tuning e Retroalimentação com RAG e TensorFlow.
4. Controle do Fallback Humano Imediato (Human Takeover & Pausa Automática).
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple
from app import db
from app.models import MessageLog, Client, FineTuningPair, Setting
from app.tasks.queue import get_redis_connection
from app.utils.conversation_memory import ConversationMemory

logger = logging.getLogger(__name__)

REDIS_PREFIX_TAKEOVER = "crm:wa:human_takeover"
REDIS_PREFIX_FAILS = "crm:wa:fail_count"
TAKEOVER_DEFAULT_TTL = 86400  # 24 horas de pausa para intervenção humana


class DialogueCollector:
    """Coletor inteligente de diálogos e orquestrador de pares para Fine-Tuning."""

    @classmethod
    def is_human_takeover_active(cls, chat_id: str) -> bool:
        """Verifica se o chat está sob controle exclusivo do atendente humano (bot pausado)."""
        if not chat_id:
            return False
        try:
            conn = get_redis_connection()
            clean_digits = chat_id.split('@')[0]
            return bool(conn.get(f"{REDIS_PREFIX_TAKEOVER}:{chat_id}") or conn.get(f"{REDIS_PREFIX_TAKEOVER}:{clean_digits}"))
        except Exception as e:
            logger.warning(f"[DialogueCollector] Erro ao checar takeover para {chat_id}: {e}")
            return False

    @classmethod
    def activate_human_takeover(cls, chat_id: str, reason: str = "solicitacao_humana") -> bool:
        """Pausa o bot imediatamente para o chat especificado e transfere para atendimento humano."""
        if not chat_id:
            return False
        try:
            conn = get_redis_connection()
            clean_digits = chat_id.split('@')[0]
            key = f"{REDIS_PREFIX_TAKEOVER}:{chat_id}"
            conn.set(key, reason, ex=TAKEOVER_DEFAULT_TTL)
            if clean_digits != chat_id:
                conn.set(f"{REDIS_PREFIX_TAKEOVER}:{clean_digits}", reason, ex=TAKEOVER_DEFAULT_TTL)
            logger.info(f"[DialogueCollector] 🚨 Transbordo Humano ATIVADO para '{chat_id}'. Motivo: {reason}")

            # Registra evento na telemetria LiveTracker
            try:
                from app.utils.live_tracker import LiveTracker
                LiveTracker.emit_step(
                    batch_id=f"takeover_{chat_id[-6:]}",
                    chat_id=chat_id,
                    step="human_takeover",
                    status="active",
                    details={"reason": reason, "paused_at": datetime.now().isoformat()}
                )
            except Exception:
                pass

            return True
        except Exception as e:
            logger.error(f"[DialogueCollector] Erro ao ativar takeover para {chat_id}: {e}")
            return False

    @classmethod
    def deactivate_human_takeover(cls, chat_id: str) -> bool:
        """Retoma as respostas automáticas do bot para o chat especificado."""
        if not chat_id:
            return False
        try:
            conn = get_redis_connection()
            clean_digits = chat_id.split('@')[0]
            conn.delete(f"{REDIS_PREFIX_TAKEOVER}:{chat_id}")
            conn.delete(f"{REDIS_PREFIX_FAILS}:{chat_id}")
            if clean_digits != chat_id:
                conn.delete(f"{REDIS_PREFIX_TAKEOVER}:{clean_digits}")
                conn.delete(f"{REDIS_PREFIX_FAILS}:{clean_digits}")
            logger.info(f"[DialogueCollector] 🤖 Bot RETOMADO para '{chat_id}'. Atendimento automático reativado.")
            return True
        except Exception as e:
            logger.error(f"[DialogueCollector] Erro ao desativar takeover para {chat_id}: {e}")
            return False

    @classmethod
    def register_failure_and_check_takeover(cls, chat_id: str, reason: str = "interpretacao_falha") -> bool:
        """
        Incrementa contador de falhas consecutivas de interpretação do bot.
        Se atingir 2 falhas, ativa automaticamente o fallback humano imediato.
        Retorna True se o takeover foi acionado.
        """
        if not chat_id:
            return False
        try:
            conn = get_redis_connection()
            fail_key = f"{REDIS_PREFIX_FAILS}:{chat_id}"
            count = conn.incr(fail_key)
            conn.expire(fail_key, 3600)  # Janela de 1 hora para falhas consecutivas

            logger.warning(f"[DialogueCollector] Falha consecutiva do bot registrada para '{chat_id}' (Contagem: {count}/2)")
            if count >= 2:
                cls.activate_human_takeover(chat_id, reason=f"bot_falhou_repetidamente ({reason})")
                return True
        except Exception as e:
            logger.error(f"[DialogueCollector] Erro ao registrar falha para {chat_id}: {e}")
        return False

    @classmethod
    def reset_failures(cls, chat_id: str):
        """Zera a contagem de falhas do bot quando uma resposta bem-sucedida ocorre."""
        try:
            conn = get_redis_connection()
            conn.delete(f"{REDIS_PREFIX_FAILS}:{chat_id}")
        except Exception:
            pass

    @classmethod
    def process_outbound_human_message(cls, chat_id: str, body: str, raw_payload: dict, instance_id: Any = None) -> Dict[str, Any]:
        """
        Processa mensagens enviadas pelo operador humano (fromMe=True).
        1. Persiste no MessageLog como 'outbound' do atendente humano.
        2. Atualiza a memória de conversação.
        3. Captura o par de diálogo com a última mensagem inbound do cliente (Fine-Tuning Dataset).
        """
        if not body or not body.strip():
            return {"status": "ignored", "reason": "empty_outbound_body"}

        clean_text = body.strip()

        # 1. Localiza cliente correspondente
        from app.utils.lead_enricher import LeadEnricher
        clean_phone = LeadEnricher.clean_digits(chat_id)
        client = LeadEnricher.find_client_by_phone(clean_phone or chat_id)

        # 2. Persiste MessageLog do atendente humano
        outbound_log = None
        try:
            from app.tasks.whatsapp import _resolve_waha_instance_pk
            outbound_log = MessageLog(
                client_id=client.id if client else None,
                user_id=None,
                content=clean_text,
                channel='whatsapp_human',
                status='sent',
                direction='outbound',
                chat_id=chat_id,
                timestamp=datetime.now(timezone.utc),
                waha_instance_id=_resolve_waha_instance_pk(instance_id)
            )
            db.session.add(outbound_log)
            db.session.commit()
            logger.info(f"[DialogueCollector] Mensagem humana outbound gravada: ID={outbound_log.id} para Chat={chat_id}")
        except Exception as e:
            db.session.rollback()
            logger.error(f"[DialogueCollector] Erro ao salvar MessageLog humano: {e}")

        # 2.1 Pausa automaticamente o bot para permitir que o atendente humano conduza o diálogo
        try:
            cls.activate_human_takeover(chat_id, reason="intervencao_humana_outbound")
            if client and client.bot_enabled:
                client.bot_enabled = False
                db.session.commit()
                logger.info(f"[DialogueCollector] Lead ID={client.id} alternado para modo 'Humano' após envio de mensagem pelo operador.")
        except Exception as e:
            logger.warning(f"[DialogueCollector] Erro ao pausar bot após envio humano: {e}")

        # 3. Atualiza memória conversacional multi-turno
        try:
            # Registra na memória do Redis que a última resposta foi do atendente
            ConversationMemory.record_turn(
                chat_id=chat_id,
                user_content="[Interação registrada]",
                assistant_content=clean_text
            )
        except Exception as e:
            logger.warning(f"[DialogueCollector] Erro ao atualizar memória com resposta humana: {e}")

        # 4. Formação do Par de Diálogo (Gold Standard Pair: Lead Inbound -> Human Outbound)
        pair = None
        try:
            # Busca a última mensagem inbound do lead nas últimas 48 horas
            cutoff = datetime.utcnow() - timedelta(hours=48)
            last_inbound = MessageLog.query.filter(
                MessageLog.chat_id == chat_id,
                MessageLog.direction == 'inbound',
                MessageLog.timestamp >= cutoff
            ).order_by(MessageLog.timestamp.desc()).first()

            if last_inbound and last_inbound.content and last_inbound.content.strip():
                lead_prompt = last_inbound.content.strip()

                # Busca rascunho anterior que o bot eventualmente havia gerado
                last_bot_draft = MessageLog.query.filter(
                    MessageLog.chat_id == chat_id,
                    MessageLog.direction == 'outbound',
                    MessageLog.channel == 'waha_api',
                    MessageLog.timestamp >= last_inbound.timestamp
                ).order_by(MessageLog.timestamp.desc()).first()

                bot_draft_text = last_bot_draft.content if last_bot_draft else None

                # Analisa intenção e sentimento com o TensorFlow Engine
                from app.utils.tf_engine import TensorFlowEngine
                tf_analysis = TensorFlowEngine.classify_sentiment_and_intent(lead_prompt)

                # Verifica se já existe par idêntico pendente para atualizar ou criar novo
                existing_pair = FineTuningPair.query.filter_by(
                    chat_id=chat_id,
                    lead_prompt=lead_prompt
                ).first()

                if existing_pair:
                    existing_pair.human_response = clean_text
                    existing_pair.bot_draft = bot_draft_text or existing_pair.bot_draft
                    existing_pair.intent_detected = tf_analysis.get('intent')
                    existing_pair.sentiment_detected = tf_analysis.get('sentiment')
                    existing_pair.updated_at = datetime.utcnow()
                    pair = existing_pair
                    logger.info(f"[DialogueCollector] Par de Fine-Tuning ID={pair.id} atualizado com resposta humana.")
                else:
                    pair = FineTuningPair(
                        client_id=client.id if client else None,
                        chat_id=chat_id,
                        lead_prompt=lead_prompt,
                        bot_draft=bot_draft_text,
                        human_response=clean_text,
                        intent_detected=tf_analysis.get('intent'),
                        sentiment_detected=tf_analysis.get('sentiment'),
                        status='pending',
                        quality_score=5,
                        source='waha_capture',
                        created_at=datetime.utcnow()
                    )
                    db.session.add(pair)
                    logger.info(f"[DialogueCollector] Novo Par de Diálogo Ouro capturado para Fine-Tuning: Chat={chat_id}")

                db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"[DialogueCollector] Erro ao criar/atualizar FineTuningPair: {e}", exc_info=True)

        return {
            'status': 'recorded_human_message',
            'chat_id': chat_id,
            'message_log_id': outbound_log.id if outbound_log else None,
            'finetuning_pair_id': pair.id if pair else None
        }
