"""
Módulo de Processamento e Envio de Mensagens de WhatsApp (WAHA + Ollama + CRM).

Responsabilidades:
1. Processamento em Lote (_do_process_buffered_whatsapp_messages):
   - Valida idempotência por token de batch.
   - Adquire mutex distribuído (lock) no Redis para evitar condições de corrida.
   - Consome mensagens acumuladas na janela de silêncio e as agrega em um texto coeso.
   - Ativa presença no WhatsApp: Confirmação visual de leitura (seen) e simulação de 'digitando...'.
   - Localiza o cliente no CRM ou realiza auto-cadastro como lead.
   - Aplica regras de negócio: Validação de horário comercial e gatilhos de transbordo humano.
   - Constrói o contexto multi-turno a partir do histórico preservado no Redis.
   - Aciona o modelo de IA local (Ollama com Llama 3.2) para gerar respostas precisas.
   - Envia a resposta final sintetizada via API do WAHA e grava MessageLog no PostgreSQL.
   - Emite telemetria em tempo real para o monitor gráfico (LiveTracker).

2. Processamento Imediato / Legado (_do_process_whatsapp_message):
   - Utilizado para mensagens avulsas sem janela de debounce quando aplicável.
"""

import json
import logging
import time
from datetime import datetime, timezone
from flask import current_app

logger = logging.getLogger(__name__)

def _extract_message_id(payload):
    """Extrai o ID da mensagem com suporte a string ou dicionário de serialização do WAHA."""
    raw_id = payload.get('id') or payload.get('message_id')
    if isinstance(raw_id, dict):
        return raw_id.get('_serialized') or raw_id.get('id') or str(raw_id)
    return str(raw_id) if raw_id else None

def _clean_phone_number(raw_phone):
    """Limpa e formata o número do remetente, removendo sufixos como @c.us e caracteres especiais."""
    if not raw_phone:
        return ""
    phone_clean = raw_phone.split('@')[0]
    return ''.join(filter(str.isdigit, phone_clean))

def _resolve_waha_instance_pk(instance_id):
    """
    Traduz instance_id (que pode ser string como 'default' ou ID numérico)
    para a Primary Key inteira da tabela WahaInstance no PostgreSQL.
    Evita erros de coerção de tipo (DataError) ao salvar MessageLog.
    """
    if not instance_id:
        return None
    if isinstance(instance_id, int) or (isinstance(instance_id, str) and instance_id.isdigit()):
        return int(instance_id)
    try:
        from app.models import WahaInstance
        inst = WahaInstance.query.filter_by(session_name=str(instance_id)).first()
        if inst:
            return inst.id
        default_inst = WahaInstance.query.filter_by(is_default=True).first() or WahaInstance.query.first()
        return default_inst.id if default_inst else None
    except Exception:
        return None

def _do_process_whatsapp_message(payload, event=None, instance_id=None):
    """Execução interna do processamento da mensagem dentro do contexto do Flask."""
    from app import db
    from app.models import Client, MessageLog
    from app.utils.ai_handler import AIHandler
    from app.utils.waha import WahaAPI

    start_time = time.time()
    msg_id = _extract_message_id(payload)
    from_raw = payload.get('from', '')
    body = payload.get('body', '')
    is_from_me = payload.get('fromMe', False)
    participant = payload.get('participant')
    is_group = '@g.us' in from_raw or bool(participant) or payload.get('isGroup', False)
    is_broadcast = '@broadcast' in from_raw or from_raw == 'status@broadcast'

    logger.info(f"[Task WhatsApp] Iniciando processamento de mensagem: ID={msg_id}, From={from_raw}, FromMe={is_from_me}, Group={is_group}")

    # 1. Filtros de descarte de mensagens
    if is_from_me:
        logger.info(f"[Task WhatsApp] Mensagem enviada pelo próprio número (fromMe=True). Ignorando: ID={msg_id}")
        return {"status": "ignored", "reason": "sent_by_me", "message_id": msg_id}

    if is_group:
        logger.info(f"[Task WhatsApp] Mensagem proveniente de grupo de WhatsApp. Ignorando: ID={msg_id}")
        return {"status": "ignored", "reason": "group_message", "message_id": msg_id}

    if is_broadcast:
        logger.info(f"[Task WhatsApp] Mensagem de broadcast/status ignorada: ID={msg_id}")
        return {"status": "ignored", "reason": "broadcast", "message_id": msg_id}

    if not body or not body.strip():
        logger.info(f"[Task WhatsApp] Mensagem sem conteúdo de texto. Ignorando: ID={msg_id}")
        return {"status": "ignored", "reason": "empty_body", "message_id": msg_id}

    if not from_raw:
        logger.warning(f"[Task WhatsApp] Mensagem sem campo 'from'. Ignorando: ID={msg_id}")
        return {"status": "ignored", "reason": "missing_from", "message_id": msg_id}

    clean_digits = _clean_phone_number(from_raw)
    
    # 2. Localização do cliente no banco de dados (por sufixo de 8 ou 9 dígitos)
    client = None
    if len(clean_digits) >= 8:
        phone_suffix = clean_digits[-8:]
        client = Client.query.filter(Client.phone.contains(phone_suffix)).first()
        if client:
            logger.info(f"[Task WhatsApp] Cliente identificado: ID={client.id}, Nome='{client.name}', Telefone='{client.phone}'")
        else:
            logger.info(f"[Task WhatsApp] Telefone {clean_digits} não cadastrado na base de clientes.")

    # 3. Geração de resposta via Inteligência Artificial
    ai_start = time.time()
    try:
        reply_text, ai_error = AIHandler.generate_reply(body.strip())
        ai_duration = round((time.time() - ai_start) * 1000, 2)
        if ai_error:
            logger.warning(f"[Task WhatsApp] Aviso/Erro na geração da IA ({ai_duration}ms): {ai_error}")
        else:
            logger.info(f"[Task WhatsApp] IA gerou resposta em {ai_duration}ms: '{reply_text[:60]}...'")
    except Exception as e:
        ai_duration = round((time.time() - ai_start) * 1000, 2)
        logger.error(f"[Task WhatsApp] Exceção crítica na IA ({ai_duration}ms): {e}", exc_info=True)
        reply_text = "Olá! Recebemos sua mensagem e um de nossos atendentes entrará em contato em instantes."

    if not reply_text or not reply_text.strip():
        reply_text = "Olá! Recebemos sua mensagem e entraremos em contato em breve."

    # 4. Envio da resposta via WAHA API
    send_start = time.time()
    success, api_response = False, None
    try:
        # Garante destino com formato compatível com o WAHA (geralmente o próprio from_raw ou telefone limpo)
        target_chat_id = from_raw if '@' in from_raw else f"{clean_digits}@c.us"
        success, api_response = WahaAPI.send_text(target_chat_id, reply_text, instance_id=instance_id)
        send_duration = round((time.time() - send_start) * 1000, 2)
        logger.info(f"[Task WhatsApp] Envio WAHA ({send_duration}ms): Sucesso={success}")
    except Exception as e:
        send_duration = round((time.time() - send_start) * 1000, 2)
        logger.error(f"[Task WhatsApp] Erro ao enviar mensagem via WAHA ({send_duration}ms): {e}", exc_info=True)
        api_response = {"error": str(e)}

    # 5. Registro de auditoria no banco de dados (MessageLog)
    try:
        raw_response_str = json.dumps(api_response) if isinstance(api_response, (dict, list)) else str(api_response)
        log = MessageLog(
            client_id=client.id if client else None,
            user_id=None,
            content=reply_text,
            channel='waha_api',
            status='sent' if success else 'error',
            timestamp=datetime.now(timezone.utc),
            api_response=raw_response_str,
            waha_instance_id=_resolve_waha_instance_pk(instance_id)
        )
        db.session.add(log)
        db.session.commit()
        logger.info(f"[Task WhatsApp] Log de mensagem gravado no banco: ID={log.id}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"[Task WhatsApp] Falha ao persistir MessageLog no banco: {e}", exc_info=True)

    total_duration = round((time.time() - start_time) * 1000, 2)
    logger.info(f"[Task WhatsApp] Processamento concluído em {total_duration}ms para ID={msg_id}")

    return {
        "status": "completed",
        "message_id": msg_id,
        "sent": success,
        "reply": reply_text,
        "client_id": client.id if client else None,
        "duration_ms": total_duration
    }

def process_whatsapp_message(payload, event=None, instance_id=None):
    """
    Função principal executada pelo RQ Worker para mensagens avulsas (modo legado/imediato).
    Garante que o contexto da aplicação Flask esteja ativo e configurado.
    """
    try:
        from flask import current_app
        if current_app:
            return _do_process_whatsapp_message(payload, event, instance_id)
    except RuntimeError:
        pass

    # Se estiver rodando isolado no worker sem contexto Flask pré-estabelecido
    from app import create_app
    flask_app = create_app()
    with flask_app.app_context():
        return _do_process_whatsapp_message(payload, event, instance_id)


def _do_process_buffered_whatsapp_messages(chat_id: str, batch_token: str, instance_id: str = None):
    """
    Execução do lote consolidado de mensagens após a janela de silêncio (debounce).
    Forma contexto unificado, consulta histórico no Redis, aciona o Ollama e envia via WAHA.
    """
    from app import db
    from app.models import Client, MessageLog, Setting
    from app.tasks.buffer import is_valid_batch, acquire_chat_lock, release_chat_lock, pop_all_buffered_messages
    from app.utils.ai_handler import AIHandler
    from app.utils.conversation_memory import ConversationMemory
    from app.utils.waha import WahaAPI

    start_time = time.time()
    logger.info(f"[Task WhatsApp Batch] Verificando token '{batch_token}' para chat '{chat_id}'...")

    # 1. Validação de token de debounce: se outro job mais novo foi agendado, encerra silenciosamente
    if not is_valid_batch(chat_id, batch_token):
        logger.info(f"[Task WhatsApp Batch] Batch token '{batch_token}' desatualizado para '{chat_id}'. Descartando job antigo.")
        return {"status": "skipped", "reason": "token_superseded", "chat_id": chat_id}

    # 2. Mutex Lock atômico no Redis
    if not acquire_chat_lock(chat_id, timeout_seconds=45):
        logger.warning(f"[Task WhatsApp Batch] Não foi possível adquirir lock para '{chat_id}'. Em execução por outro processo.")
        return {"status": "skipped", "reason": "locked", "chat_id": chat_id}

    try:
        # 3. Extrai todas as mensagens acumuladas no buffer durante a janela de debounce
        messages = pop_all_buffered_messages(chat_id)
        if not messages:
            logger.info(f"[Task WhatsApp Batch] Buffer vazio para '{chat_id}'. Encerrando.")
            return {"status": "empty_buffer", "chat_id": chat_id}

        bodies = [m.get('body', '').strip() for m in messages if m.get('body', '').strip()]
        if not bodies:
            logger.info(f"[Task WhatsApp Batch] Nenhuma mensagem com texto válido para '{chat_id}'.")
            return {"status": "empty_text", "chat_id": chat_id}

        # Concatena as mensagens acumuladas formando um bloco contextual coeso
        aggregated_text = "\n".join(bodies) if len(bodies) > 1 else bodies[0]
        last_msg_id = messages[-1].get('id')
        clean_digits = _clean_phone_number(chat_id)

        logger.info(
            f"[Task WhatsApp Batch] Processando lote de {len(messages)} mensagens para '{chat_id}': "
            f"'{aggregated_text[:80]}...'"
        )

        try:
            from app.utils.live_tracker import LiveTracker, STEP_BUFFER, STEP_PRESENCE, STEP_CONTEXT, STEP_OLLAMA, STEP_DISPATCH
            LiveTracker.emit_step(
                batch_id=batch_token,
                chat_id=chat_id,
                step=STEP_BUFFER,
                status="completed",
                details={"batch_size": len(messages), "aggregated_text": aggregated_text[:120]}
            )
        except Exception:
            pass

        # 4. Verificação de Bot Ativo
        bot_enabled = Setting.get('whatsapp_bot_enabled')
        if bot_enabled is not None and str(bot_enabled).lower() in ['false', '0', 'no']:
            logger.info(f"[Task WhatsApp Batch] Bot de respostas automáticas está pausado nas configurações para '{chat_id}'.")
            return {"status": "bot_disabled", "chat_id": chat_id}

        # 5. Confirmação de Leitura e Presença no WAHA
        send_seen_cfg = Setting.get('whatsapp_send_seen')
        should_seen = True if send_seen_cfg is None else str(send_seen_cfg).lower() in ['true', '1', 'yes']
        if should_seen:
            WahaAPI.send_seen(chat_id, message_id=last_msg_id, instance_id=instance_id)

        simulate_typing = Setting.get('whatsapp_simulate_typing')
        should_type = True if simulate_typing is None else str(simulate_typing).lower() in ['true', '1', 'yes']
        if should_type:
            WahaAPI.start_typing(chat_id, instance_id=instance_id)

        try:
            from app.utils.live_tracker import LiveTracker, STEP_PRESENCE
            LiveTracker.emit_step(
                batch_id=batch_token,
                chat_id=chat_id,
                step=STEP_PRESENCE,
                status="completed",
                details={"seen_marked": should_seen, "typing_simulated": should_type}
            )
        except Exception:
            pass


        # 6. Localização ou Auto-Cadastro do Cliente no CRM
        client = None
        client_info = None
        if len(clean_digits) >= 8:
            phone_suffix = clean_digits[-8:]
            client = Client.query.filter(Client.phone.contains(phone_suffix)).first()
            if not client:
                auto_create = Setting.get('whatsapp_bot_auto_create_lead')
                if auto_create is None or str(auto_create).lower() in ['true', '1', 'yes']:
                    try:
                        client = Client(
                            name=f"Lead WA {clean_digits[-4:]}",
                            phone=clean_digits,
                            status='lead',
                            notes="Lead criado automaticamente via Bot WhatsApp."
                        )
                        db.session.add(client)
                        db.session.commit()
                        logger.info(f"[Task WhatsApp Batch] Novo Lead auto-cadastrado no CRM: ID={client.id}, Fone={clean_digits}")
                    except Exception as e:
                        db.session.rollback()
                        logger.warning(f"[Task WhatsApp Batch] Não foi possível auto-cadastrar lead: {e}")

            if client:
                client_info = {
                    'name': client.name,
                    'status': client.status,
                    'assigned_user': client.assigned_user.username if getattr(client, 'assigned_user', None) else None,
                    'segment': getattr(client, 'segment', None)
                }

        # 7. Regra de Transbordo para Atendente Humano
        triggers_raw = Setting.get('whatsapp_bot_handover_trigger') or 'humano, atendente, falar com pessoa, falar com alguem, suporte humano'
        triggers = [t.strip().lower() for t in triggers_raw.split(',') if t.strip()]
        lower_aggregated = aggregated_text.lower()
        is_handover = any(t in lower_aggregated for t in triggers)

        # 8. Regra de Horário Comercial
        is_out_of_hours = False
        work_hours_enabled = Setting.get('whatsapp_bot_work_hours_enabled')
        if work_hours_enabled and str(work_hours_enabled).lower() in ['true', '1', 'yes']:
            import zoneinfo
            try:
                tz = zoneinfo.ZoneInfo("America/Sao_Paulo")

                now_local = datetime.now(tz)
                start_h = Setting.get('whatsapp_bot_work_hours_start') or '08:00'
                end_h = Setting.get('whatsapp_bot_work_hours_end') or '18:00'
                current_hm = now_local.strftime('%H:%M')
                if current_hm < start_h or current_hm > end_h:
                    is_out_of_hours = True
            except Exception as e:
                logger.warning(f"[Task WhatsApp Batch] Erro ao validar horário comercial: {e}")

        # 9. Definição da Resposta
        reply_text = None
        if is_handover:
            reply_text = Setting.get('whatsapp_bot_handover_msg') or (
                "Com certeza! Estou direcionando seu atendimento para um de nossos consultores humanos. Em instantes alguém da equipe responderá aqui."
            )
            logger.info(f"[Task WhatsApp Batch] Transbordo humano acionado para '{chat_id}'.")
        elif is_out_of_hours:
            reply_text = Setting.get('whatsapp_bot_out_of_hours_msg') or (
                "Olá! No momento estamos fora do nosso horário de atendimento. Deixe sua mensagem que responderemos assim que retornarmos!"
            )
            logger.info(f"[Task WhatsApp Batch] Resposta fora do expediente enviada para '{chat_id}'.")
        else:
            # Carrega histórico do Redis e aciona o Ollama
            chat_history = ConversationMemory.get_context_messages(chat_id)
            logger.info(f"[Task WhatsApp Batch] Contexto multi-turno carregado: {len(chat_history)} mensagens anteriores.")

            try:
                LiveTracker.emit_step(
                    batch_id=batch_token,
                    chat_id=chat_id,
                    step=STEP_CONTEXT,
                    status="completed",
                    details={
                        "lead_name": client_info.get('name') if client_info else "Lead Não Cadastrado",
                        "history_turns": len(chat_history),
                        "lead_status": client_info.get('status') if client_info else "lead"
                    }
                )
                LiveTracker.emit_step(
                    batch_id=batch_token,
                    chat_id=chat_id,
                    step=STEP_OLLAMA,
                    status="active",
                    details={"model": Setting.get('ai_ollama_model', 'llama3.2')}
                )
            except Exception:
                pass

            fallback_msg = Setting.get('whatsapp_bot_fallback_msg') or "Olá! Recebemos sua mensagem e nossa equipe retornará em instantes."
            ai_start = time.time()
            try:
                reply_text, ai_error = AIHandler.generate_chat_reply(
                    customer_message=aggregated_text,
                    chat_history=chat_history,
                    client_info=client_info
                )
                ai_duration = round((time.time() - ai_start) * 1000, 2)
                if ai_error:
                    logger.warning(f"[Task WhatsApp Batch] Aviso da IA ({ai_duration}ms): {ai_error}")
                else:
                    logger.info(f"[Task WhatsApp Batch] IA gerou resposta em {ai_duration}ms: '{reply_text[:60]}...'")

                try:
                    LiveTracker.emit_step(
                        batch_id=batch_token,
                        chat_id=chat_id,
                        step=STEP_OLLAMA,
                        status="completed" if not ai_error else "warning",
                        details={"reply_preview": (reply_text or "")[:120], "duration_ms": ai_duration},
                        duration_ms=ai_duration
                    )
                except Exception:
                    pass
            except Exception as e:
                ai_duration = round((time.time() - ai_start) * 1000, 2)
                logger.error(f"[Task WhatsApp Batch] Exceção crítica na IA ({ai_duration}ms): {e}", exc_info=True)
                reply_text = fallback_msg
                try:
                    LiveTracker.emit_step(
                        batch_id=batch_token,
                        chat_id=chat_id,
                        step=STEP_OLLAMA,
                        status="error",
                        details={"error": str(e)[:100]},
                        duration_ms=ai_duration
                    )
                except Exception:
                    pass

            if not reply_text or not reply_text.strip():
                reply_text = fallback_msg

        # Desativa o 'digitando...' antes de enviar
        if should_type:
            WahaAPI.stop_typing(chat_id, instance_id=instance_id)

        # 10. Envio da resposta final sintetizada via WAHA
        send_start = time.time()
        success, api_response = False, None
        try:
            target_chat_id = chat_id if '@' in chat_id else f"{clean_digits}@c.us"

            success, api_response = WahaAPI.send_text(target_chat_id, reply_text, instance_id=instance_id)
            send_duration = round((time.time() - send_start) * 1000, 2)
            logger.info(f"[Task WhatsApp Batch] Resposta enviada via WAHA ({send_duration}ms): Sucesso={success}")
        except Exception as e:
            send_duration = round((time.time() - send_start) * 1000, 2)
            logger.error(f"[Task WhatsApp Batch] Erro ao enviar resposta via WAHA: {e}", exc_info=True)
            api_response = {"error": str(e)}

        # 9. Salva o turno na memória do Redis (para que futuras mensagens tenham contexto)
        if success:
            ConversationMemory.record_turn(chat_id, aggregated_text, reply_text)

        # 10. Registro no banco de dados (MessageLog)
        try:
            raw_response_str = json.dumps(api_response) if isinstance(api_response, (dict, list)) else str(api_response)
            log = MessageLog(
                client_id=client.id if client else None,
                user_id=None,
                content=f"[Lote {len(messages)} msgs]\n{reply_text}",
                channel='waha_api',
                status='sent' if success else 'error',
                timestamp=datetime.now(timezone.utc),
                api_response=raw_response_str,
                waha_instance_id=_resolve_waha_instance_pk(instance_id)
            )
            db.session.add(log)
            db.session.commit()
            logger.info(f"[Task WhatsApp Batch] MessageLog gravado no banco: ID={log.id}")
        except Exception as e:
            db.session.rollback()
            logger.error(f"[Task WhatsApp Batch] Falha ao persistir MessageLog: {e}", exc_info=True)

        total_duration = round((time.time() - start_time) * 1000, 2)
        logger.info(f"[Task WhatsApp Batch] Lote concluído em {total_duration}ms para '{chat_id}'.")

        try:
            LiveTracker.emit_step(
                batch_id=batch_token,
                chat_id=chat_id,
                step=STEP_DISPATCH,
                status="completed" if success else "error",
                details={
                    "success": success,
                    "target": target_chat_id,
                    "reply_text": reply_text,
                    "total_duration_ms": total_duration
                },
                duration_ms=total_duration
            )
        except Exception:
            pass


        total_duration = round((time.time() - start_time) * 1000, 2)
        logger.info(f"[Task WhatsApp Batch] Lote concluído em {total_duration}ms para '{chat_id}'.")

        return {
            "status": "completed",
            "chat_id": chat_id,
            "batch_size": len(messages),
            "sent": success,
            "reply": reply_text,
            "duration_ms": total_duration
        }

    finally:
        # Garante liberação do lock em qualquer cenário
        release_chat_lock(chat_id)


def process_buffered_whatsapp_messages(chat_id: str, batch_token: str, instance_id: str = None):
    """
    Função principal executada pelo RQ Worker para processamento em lote com debounce.
    Garante que o contexto da aplicação Flask esteja ativo e configurado.
    """
    try:
        from flask import current_app
        if current_app:
            return _do_process_buffered_whatsapp_messages(chat_id, batch_token, instance_id)
    except RuntimeError:
        pass

    from app import create_app
    flask_app = create_app()
    with flask_app.app_context():
        return _do_process_buffered_whatsapp_messages(chat_id, batch_token, instance_id)

