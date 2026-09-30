"""
Motor de Disparo em Lote Desacoplado (Bulk Message Engine) para WAHA.

Principais Recursos:
1. Desacoplamento Total: Executa em Background Thread resiliente com contexto do Flask.
2. Controles de Ciclo de Vida: Iniciar, Pausar, Retomar, Cancelar e Master Switch ON/OFF global.
3. Circuit Breaker Anti-Ban: Pausa emergencial automática após falhas consecutivas ou violação de cotas.
4. Spintax & Variáveis Ricas: Variação natural do texto ({Olá|Oi|Bom dia}) e saudações dinâmicas.
5. Pausas Táticas (Cool-off): Descanço programado a cada lote de envios para emular comportamento humano.
6. Telemetria em Tempo Real: Métricas de velocidade (msgs/min), ETA e logs para polling contínuo da UI.
"""

import re
import time
import random
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional

from flask import current_app

logger = logging.getLogger(__name__)

# Dicionário de controle das threads ativas por campanha: campaign_id -> threading.Event (stop/pause signal)
_active_campaign_events: Dict[int, threading.Event] = {}
_campaign_telemetry: Dict[int, Dict[str, Any]] = {}
_engine_lock = threading.Lock()


# ── Utilitários de Texto: Spintax & Variáveis Dinâmicas ────────────────────────

def resolve_spintax(text: str) -> str:
    """
    Resolve sintaxe Spintax aninhada recursivamente.
    Exemplo: "{Olá|Oi|E aí}, {tudo bem|como vai}?" -> "Olá, como vai?"
    """
    if not text:
        return ""
    pattern = re.compile(r'\{([^{}]+)\}')
    
    # Executa até substituir todas as ocorrências de Spintax
    while True:
        match = pattern.search(text)
        if not match:
            break
        choices = match.group(1).split('|')
        chosen = random.choice(choices)
        text = text[:match.start()] + chosen + text[match.end():]
        
    return text


def get_time_greeting() -> str:
    """Retorna saudação conforme o horário atual local (05-12: Bom dia, 12-18: Boa tarde, 18-05: Boa noite)."""
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "Bom dia"
    elif 12 <= hour < 18:
        return "Boa tarde"
    else:
        return "Boa noite"


def resolve_message_variables(template_text: str, recipient, client=None) -> str:
    """
    Substitui todas as tags dinâmicas no texto da mensagem por dados do contato/lead.
    Tags suportadas:
    - [NOME], [PRIMEIRO_NOME]
    - [NOME_COMPLETO]
    - [SAUDACAO_HORARIO]
    - [STATUS]
    - [EMPRESA], [SEGMENTO]
    - [CIDADE]
    - [DATA], [HORA]
    """
    if not template_text:
        return ""

    raw_name = (recipient.name or (client.name if client else '') or 'Cliente').strip()
    first_name = raw_name.split()[0] if raw_name else 'Cliente'
    status_str = (client.status if client and client.status else '').capitalize()
    segment_str = (client.display_segment if client and hasattr(client, 'display_segment') else (client.segment if client else '')) or ''
    city_str = ''
    if client and client.address:
        parts = client.address.split('-')
        if len(parts) > 1:
            city_str = parts[-1].strip()

    now = datetime.now()
    date_str = now.strftime('%d/%m/%Y')
    time_str = now.strftime('%H:%M')
    greeting = get_time_greeting()

    resolved = template_text
    resolved = re.sub(r'\[NOME\]', first_name, resolved, flags=re.IGNORECASE)
    resolved = re.sub(r'\[PRIMEIRO_NOME\]', first_name, resolved, flags=re.IGNORECASE)
    resolved = re.sub(r'\[NOME_COMPLETO\]', raw_name, resolved, flags=re.IGNORECASE)
    resolved = re.sub(r'\[SAUDACAO_HORARIO\]', greeting, resolved, flags=re.IGNORECASE)
    resolved = re.sub(r'\[STATUS\]', status_str, resolved, flags=re.IGNORECASE)
    resolved = re.sub(r'\[EMPRESA\]', segment_str, resolved, flags=re.IGNORECASE)
    resolved = re.sub(r'\[SEGMENTO\]', segment_str, resolved, flags=re.IGNORECASE)
    resolved = re.sub(r'\[CIDADE\]', city_str, resolved, flags=re.IGNORECASE)
    resolved = re.sub(r'\[DATA\]', date_str, resolved, flags=re.IGNORECASE)
    resolved = re.sub(r'\[HORA\]', time_str, resolved, flags=re.IGNORECASE)

    # Processa Spintax após substituição de variáveis
    resolved = resolve_spintax(resolved)
    return resolved


# ── Telemetria e Logs da Campanha ──────────────────────────────────────────────

def _init_telemetry(campaign_id: int):
    with _engine_lock:
        if campaign_id not in _campaign_telemetry:
            _campaign_telemetry[campaign_id] = {
                'logs': [],
                'speed_mpm': 0.0,
                'eta_seconds': 0,
                'start_time': time.time(),
                'last_sent_time': None,
                'recent_timestamps': []
            }


def push_telemetry_log(campaign_id: int, message: str, level: str = 'info'):
    """Registra um evento de log volátil com timestamp para visualização rápida no painel."""
    _init_telemetry(campaign_id)
    with _engine_lock:
        t_data = _campaign_telemetry[campaign_id]
        time_str = datetime.now().strftime('%H:%M:%S')
        t_data['logs'].append({
            'time': time_str,
            'message': message,
            'level': level
        })
        # Mantém apenas os últimos 150 logs em memória
        if len(t_data['logs']) > 150:
            t_data['logs'] = t_data['logs'][-150:]


def get_campaign_telemetry(campaign_id: int) -> Dict[str, Any]:
    with _engine_lock:
        t_data = _campaign_telemetry.get(campaign_id, {
            'logs': [],
            'speed_mpm': 0.0,
            'eta_seconds': 0
        })
        return {
            'logs': list(t_data.get('logs', [])),
            'speed_mpm': t_data.get('speed_mpm', 0.0),
            'eta_seconds': t_data.get('eta_seconds', 0)
        }


def _update_speed_and_eta(campaign_id: int, remaining_count: int):
    with _engine_lock:
        t_data = _campaign_telemetry.get(campaign_id)
        if not t_data:
            return
        
        now = time.time()
        stamps = t_data.get('recent_timestamps', [])
        stamps.append(now)
        # Mantém registros dos últimos 3 minutos para cálculo de média móvel
        stamps = [s for s in stamps if now - s <= 180]
        t_data['recent_timestamps'] = stamps

        if len(stamps) >= 2:
            elapsed_minutes = (stamps[-1] - stamps[0]) / 60.0
            if elapsed_minutes > 0:
                speed = round(len(stamps) / elapsed_minutes, 1)
                t_data['speed_mpm'] = speed
                if speed > 0 and remaining_count > 0:
                    t_data['eta_seconds'] = int((remaining_count / speed) * 60)
                else:
                    t_data['eta_seconds'] = 0


# ── Master Switch e Controle Global (Desligamento Seguro) ──────────────────────

def is_master_switch_enabled() -> bool:
    """Verifica se a chave mestra global do motor está ligada."""
    try:
        from app.models import Setting
        val = Setting.get_val('bulk_engine_master_enabled', 'true')
        return str(val).lower() in ('true', '1', 'yes', 'on')
    except Exception as e:
        logger.warning(f"[BulkEngine] Falha ao consultar master switch: {e}")
        return True


def is_bulk_module_enabled() -> bool:
    """Verifica se o módulo waha_bulk e a chave mestra estão ambos ativados."""
    try:
        from app.core.module_registry import is_module_enabled
        if not is_module_enabled('waha') or not is_module_enabled('waha_bulk'):
            return False
    except Exception:
        pass
    return is_master_switch_enabled()


def freeze_engine_gracefully(reason: str = "Módulo desligado com segurança") -> int:
    """
    Congela todas as campanhas em andamento de forma segura (graceful pause):
    1. Sinaliza parada imediata de todas as threads ativas.
    2. Atualiza no banco de dados todas as campanhas 'running' para 'paused' com o motivo.
    3. Preserva 100% dos contatos da fila ('pending'), sem perda de dados e sem disparos indevidos.
    Retorna o número de campanhas pausadas.
    """
    with _engine_lock:
        for cid, evt in list(_active_campaign_events.items()):
            evt.set()
            push_telemetry_log(cid, f"⏸ {reason}", "warning")

    try:
        from app import db
        from app.models import BulkCampaign
        running_campaigns = BulkCampaign.query.filter_by(status='running').all()
        paused_count = 0
        for c in running_campaigns:
            c.status = 'paused'
            c.pause_reason = reason
            paused_count += 1
        db.session.commit()
        logger.info(f"[BulkEngine] {paused_count} campanhas congeladas com sucesso: {reason}")
        return paused_count
    except Exception as e:
        logger.error(f"[BulkEngine] Erro ao congelar campanhas: {e}")
        return 0


def set_master_switch(enabled: bool):
    """Ativa ou desativa a chave mestra global. Se desativar, congela com segurança todas as campanhas ativas."""
    from app.models import Setting
    val_str = 'true' if enabled else 'false'
    Setting.set_val('bulk_engine_master_enabled', val_str, 'Chave geral do Motor de Disparo em Lote')
    
    if not enabled:
        freeze_engine_gracefully("Motor desativado pelo Administrador (Master Switch OFF)")


# ── Worker de Execução da Campanha em Background ──────────────────────────────

def _run_campaign_worker(app, campaign_id: int):
    """
    Função principal executada dentro da Background Thread.
    Mantém o contexto do Flask para acesso seguro ao SQLAlchemy, Redis e WAHA.
    """
    with app.app_context():
        from app import db
        from app.models import BulkCampaign, BulkCampaignRecipient, WahaInstance, MessageLog, Client
        from app.utils.waha import WahaAPI
        from app.utils.ai_handler import AIHandler

        campaign = BulkCampaign.query.get(campaign_id)
        if not campaign:
            logger.error(f"[BulkEngine] Campanha {campaign_id} não encontrada.")
            return

        stop_event = _active_campaign_events.get(campaign_id)
        if not stop_event:
            stop_event = threading.Event()
            _active_campaign_events[campaign_id] = stop_event

        _init_telemetry(campaign_id)
        push_telemetry_log(campaign_id, f"🚀 Motor desacoplado ativado para a campanha '{campaign.name}'.", "info")

        instance = campaign.waha_instance
        if not instance and campaign.waha_instance_id:
            instance = WahaInstance.query.get(campaign.waha_instance_id)
        if not instance:
            instance = WahaInstance.query.filter_by(is_default=True).first() or WahaInstance.query.first()

        batch_count_since_cooloff = 0

        while not stop_event.is_set():
            # 1. Verifica Módulo e Chave Mestra
            if not is_bulk_module_enabled():
                push_telemetry_log(campaign_id, "⛔ Módulo ou Chave Mestra desligados. Motor congelando campanha com segurança...", "warning")
                campaign.status = 'paused'
                campaign.pause_reason = "Módulo desativado com segurança pelo operador"
                db.session.commit()
                break

            # 2. Busca próximo destinatário pendente
            recipient = BulkCampaignRecipient.query.filter_by(
                campaign_id=campaign.id,
                status='pending'
            ).order_by(BulkCampaignRecipient.id.asc()).first()

            if not recipient:
                # Fila concluída
                campaign.status = 'completed'
                campaign.completed_at = datetime.utcnow()
                db.session.commit()
                push_telemetry_log(campaign_id, "🎉 Campanha concluída com sucesso! Todos os destinatários foram processados.", "success")
                break

            # 3. Validações Anti-Ban e Horário Silencioso da Instância
            if instance and instance.enable_anti_ban:
                can_send, reason, stats = instance.check_anti_ban_limits()
                if not can_send:
                    push_telemetry_log(campaign_id, f"⛔ Pausa Anti-Ban na instância '{instance.name}': {reason}", "warning")
                    campaign.status = 'paused'
                    campaign.pause_reason = f"Proteção Anti-Ban: {reason}"
                    db.session.commit()
                    break

            # 4. Resolve mensagem final (Variáveis + Spintax + IA)
            client = recipient.client
            final_text = resolve_message_variables(campaign.message_text, recipient, client)

            if campaign.use_ai:
                try:
                    ai_text, ai_err = AIHandler.rewrite_message(final_text)
                    if not ai_err and ai_text:
                        final_text = ai_text
                except Exception as e:
                    logger.warning(f"[BulkEngine] Erro ao reescrever mensagem com IA: {e}")

            recipient.resolved_message = final_text
            recipient.status = 'processing'
            recipient.attempts += 1
            db.session.commit()

            push_telemetry_log(campaign_id, f"Enviando para {recipient.name or 'Contato'} ({recipient.phone})...", "info")

            # 5. Envio via API do WAHA
            instance_pk = instance.id if instance else None
            success, response = WahaAPI.send_text(recipient.phone, final_text, instance_pk)

            if success:
                recipient.status = 'sent'
                recipient.sent_at = datetime.utcnow()
                recipient.waha_message_id = str(response.get('id', '')) if isinstance(response, dict) else None
                recipient.error_message = None

                campaign.success_count += 1
                campaign.processed_count += 1
                campaign.consecutive_errors = 0 # zera falhas consecutivas
                batch_count_since_cooloff += 1

                if instance:
                    instance.record_message_sent()

                # Registra log de mensagem e atualiza cliente se aplicável
                try:
                    msg_log = MessageLog(
                        client_id=recipient.client_id,
                        user_id=campaign.created_by_id,
                        content=final_text,
                        channel='whatsapp_waha',
                        status='sent',
                        waha_instance_id=instance_pk
                    )
                    db.session.add(msg_log)

                    if client:
                        client.status = "Regularização financeira"
                        now_str = datetime.now().strftime('%d/%m/%Y %H:%M')
                        client.notes = (client.notes or "") + f"\nDisparo Lote [{now_str}]: {campaign.name}"
                        client.updated_at = datetime.utcnow()
                except Exception as ex:
                    logger.error(f"[BulkEngine] Erro ao gravar log de mensagem: {ex}")

                db.session.commit()
                push_telemetry_log(campaign_id, f"✓ Sucesso ao enviar para {recipient.name or recipient.phone}", "success")
            else:
                # Falha no envio
                err_msg = str(response.get('error', response) if isinstance(response, dict) else response)
                recipient.status = 'failed'
                recipient.error_message = err_msg[:250]

                campaign.error_count += 1
                campaign.processed_count += 1
                campaign.consecutive_errors += 1
                db.session.commit()

                push_telemetry_log(campaign_id, f"✗ Erro ao enviar para {recipient.phone}: {err_msg}", "error")

                # ── CIRCUIT BREAKER: Pausa automática de emergência ──
                if campaign.consecutive_errors >= 3:
                    campaign.status = 'paused'
                    campaign.circuit_breaker_triggered = True
                    campaign.pause_reason = "Circuit Breaker Ativado: 3 falhas consecutivas. Motor pausado para segurança do chip."
                    db.session.commit()
                    push_telemetry_log(campaign_id, "🚨 [CIRCUIT BREAKER] 3 erros seguidos detectados! Motor pausado automaticamente para resguardar seu número.", "error")
                    break

            # Atualiza telemetria de velocidade e ETA
            remaining = campaign.total_count - campaign.processed_count
            _update_speed_and_eta(campaign_id, remaining)

            # 6. Pausas Táticas (Cool-off) a cada N mensagens
            if campaign.batch_pause_every and batch_count_since_cooloff >= campaign.batch_pause_every:
                cooloff_sec = campaign.batch_pause_duration or 60
                push_telemetry_log(campaign_id, f"☕ Pausa tática anti-spam: Descansando a sessão por {cooloff_sec}s após {batch_count_since_cooloff} envios...", "warning")
                batch_count_since_cooloff = 0
                for _ in range(cooloff_sec):
                    if stop_event.is_set():
                        break
                    time.sleep(1)

            # 7. Delay entre mensagens com Jitter Humano Aleatório
            if not stop_event.is_set() and campaign.processed_count < campaign.total_count:
                min_d = campaign.min_delay or 6
                max_d = campaign.max_delay or 16
                if max_d < min_d:
                    max_d = min_d + 4
                jitter_delay = round(random.uniform(min_d, max_d), 1)
                push_telemetry_log(campaign_id, f"⏳ Aguardando {jitter_delay}s (cadência humana anti-ban)...", "info")
                
                # Sleep fracionado para responder rápido a cliques de pausa
                steps = int(jitter_delay * 10)
                for _ in range(steps):
                    if stop_event.is_set():
                        break
                    time.sleep(0.1)

        # Limpeza ao sair do loop
        with _engine_lock:
            _active_campaign_events.pop(campaign_id, None)
        logger.info(f"[BulkEngine] Worker da campanha {campaign_id} finalizado. Status={campaign.status}")


# ── Comandos de Controle da Campanha ──────────────────────────────────────────

def start_campaign_engine(campaign_id: int) -> Tuple[bool, str]:
    """Inicia a campanha em uma Background Thread desacoplada."""
    from app import db
    from app.models import BulkCampaign

    campaign = BulkCampaign.query.get(campaign_id)
    if not campaign:
        return False, "Campanha não encontrada"

    if not is_bulk_module_enabled():
        return False, "O Módulo de Disparo em Lote ou a Chave Mestra está desativado no momento."

    with _engine_lock:
        if campaign_id in _active_campaign_events and not _active_campaign_events[campaign_id].is_set():
            return False, "A campanha já está em execução no motor."

        stop_event = threading.Event()
        _active_campaign_events[campaign_id] = stop_event

        campaign.status = 'running'
        campaign.pause_reason = None
        campaign.circuit_breaker_triggered = False
        campaign.consecutive_errors = 0
        if not campaign.started_at:
            campaign.started_at = datetime.utcnow()
        db.session.commit()

        app = current_app._get_current_object()
        worker_thread = threading.Thread(
            target=_run_campaign_worker,
            args=(app, campaign_id),
            name=f"BulkCampaignWorker-{campaign_id}",
            daemon=True
        )
        worker_thread.start()

    return True, "Motor iniciado com sucesso em segundo plano."


def pause_campaign_engine(campaign_id: int, reason: str = "Pausado pelo usuário") -> Tuple[bool, str]:
    """Pausa com segurança uma campanha em execução."""
    from app import db
    from app.models import BulkCampaign

    campaign = BulkCampaign.query.get(campaign_id)
    if not campaign:
        return False, "Campanha não encontrada"

    with _engine_lock:
        if campaign_id in _active_campaign_events:
            _active_campaign_events[campaign_id].set() # avisa a thread para parar

        campaign.status = 'paused'
        campaign.pause_reason = reason
        db.session.commit()

    push_telemetry_log(campaign_id, f"⏸ {reason}", "warning")
    return True, "Comando de pausa enviado com sucesso."


def cancel_campaign_engine(campaign_id: int) -> Tuple[bool, str]:
    """Cancela a campanha e marca os registros pendentes como cancelados."""
    from app import db
    from app.models import BulkCampaign, BulkCampaignRecipient

    campaign = BulkCampaign.query.get(campaign_id)
    if not campaign:
        return False, "Campanha não encontrada"

    with _engine_lock:
        if campaign_id in _active_campaign_events:
            _active_campaign_events[campaign_id].set()

        campaign.status = 'cancelled'
        campaign.pause_reason = "Cancelado pelo operador"
        campaign.completed_at = datetime.utcnow()

        # Cancela itens pendentes
        BulkCampaignRecipient.query.filter_by(
            campaign_id=campaign_id,
            status='pending'
        ).update({'status': 'cancelled'})

        db.session.commit()

    push_telemetry_log(campaign_id, "⏹ Campanha cancelada e itens pendentes descartados.", "warning")
    return True, "Campanha cancelada com sucesso."
