from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.crm import bp
from collections import defaultdict
from datetime import datetime, timedelta
from sqlalchemy import or_, and_

import urllib.parse
from app.models import Client, SystemLog, Setting, User, Store, MessageTemplate, MessageLog, WahaInstance, ScrapingJob, BulkCampaign, BulkCampaignRecipient
from app.tasks.bulk_engine import (
    start_campaign_engine, pause_campaign_engine, cancel_campaign_engine,
    get_campaign_telemetry, is_master_switch_enabled, set_master_switch,
    resolve_spintax, resolve_message_variables
)
from app.utils.messaging import WhatsAppEngine
from app.utils.waha import WahaAPI
from app.utils.ai_handler import AIHandler
from app.utils.maps_scraper import MapsScraperClient
from app.tasks.lead_scraper import dispatch_scraping_job
from app.core.module_registry import requires_module
from app.core.plugins.event_bus import EventBus
# ── XP Awards ────────────────────────────────────────────────────────────────
XP_NOVO_CLIENTE  = 10
XP_LEAD_PROPOSTA = 20
XP_FECHAR_VENDA  = 100
XP_STATUS_MOVE   = 5

def award_xp(user, points, reason):
    user.performance_points += points
    log = SystemLog(user_id=user.id, action=f"💰 +{points} XP — {reason}")
    db.session.add(log)


# ── Clients list ──────────────────────────────────────────────────────────────
@bp.route('/clients')
@login_required
def list_clients():
    q = request.args.get('q', '').strip()
    status = request.args.get('status', '').strip()
    segment = request.args.get('segment', '').strip()
    seller_id = request.args.get('seller_id', '').strip()
    store_id = request.args.get('store_id', '').strip()
    tier = request.args.get('tier', '').strip()
    source = request.args.get('source', '').strip()
    badge = request.args.get('badge', '').strip()
    date_range = request.args.get('date_range', '').strip()

    query = Client.query

    # Busca inteligente textual
    if q:
        search_filter = or_(
            Client.name.ilike(f'%{q}%'),
            Client.phone.ilike(f'%{q}%'),
            Client.email.ilike(f'%{q}%'),
            Client.cpf.ilike(f'%{q}%'),
            Client.segment.ilike(f'%{q}%'),
            Client.category.ilike(f'%{q}%'),
            Client.notes.ilike(f'%{q}%'),
            Client.website.ilike(f'%{q}%'),
            Client.instagram.ilike(f'%{q}%')
        )
        query = query.filter(search_filter)

    # Filtros por atributos principais
    if status:
        query = query.filter(Client.status == status)

    if segment:
        query = query.filter(or_(Client.segment == segment, Client.category == segment))

    if seller_id:
        try:
            sid = int(seller_id)
            query = query.filter(or_(Client.assigned_to == sid, Client.referred_by_id == sid))
        except ValueError:
            pass

    if store_id:
        try:
            stid = int(store_id)
            query = query.filter(Client.preferred_store_id == stid)
        except ValueError:
            pass

    if tier:
        query = query.filter(Client.tier == tier)

    if source:
        if source == 'gmaps':
            query = query.filter(Client.badges.ilike('%outbound_gmaps%'))
        else:
            query = query.filter(Client.lead_source == source)

    if badge:
        query = query.filter(Client.badges.contains(badge))

    if date_range:
        now = datetime.utcnow()
        if date_range == 'today':
            query = query.filter(Client.created_at >= now.replace(hour=0, minute=0, second=0, microsecond=0))
        elif date_range == '7days':
            query = query.filter(Client.created_at >= now - timedelta(days=7))
        elif date_range == '30days':
            query = query.filter(Client.created_at >= now - timedelta(days=30))

    clients = query.order_by(Client.updated_at.desc()).all()

    # Contagens para chips e métricas rápidas
    total_count = Client.query.count()
    status_counts = {
        'all': total_count,
        'lead': Client.query.filter_by(status='lead').count(),
        'contato': Client.query.filter_by(status='contato').count(),
        'proposta': Client.query.filter_by(status='proposta').count(),
        'fechado': Client.query.filter_by(status='fechado').count(),
        'perdido': Client.query.filter_by(status='perdido').count(),
    }

    # Listas auxiliares para preencher os selects
    segments_raw = db.session.query(Client.segment).filter(Client.segment.isnot(None), Client.segment != '').distinct().all()
    categories_raw = db.session.query(Client.category).filter(Client.category.isnot(None), Client.category != '').distinct().all()
    all_segments = sorted(list(set([s[0].strip() for s in segments_raw + categories_raw if s[0] and s[0].strip()])))

    users = User.query.order_by(User.username).all()
    stores = Store.query.order_by(Store.name).all()

    current_filters = {
        'q': q,
        'status': status,
        'segment': segment,
        'seller_id': seller_id,
        'store_id': store_id,
        'tier': tier,
        'source': source,
        'badge': badge,
        'date_range': date_range
    }

    has_active_filters = bool(q or status or segment or seller_id or store_id or tier or source or badge or date_range)

    return render_template(
        'crm/list.html',
        title='Gestão de Clientes e Leads',
        clients=clients,
        total_count=total_count,
        status_counts=status_counts,
        all_segments=all_segments,
        users=users,
        stores=stores,
        current_filters=current_filters,
        has_active_filters=has_active_filters,
        active_badge=badge
    )


# ── Kanban board ──────────────────────────────────────────────────────────────
@bp.route('/kanban')
@login_required
def kanban():
    q = request.args.get('q', '').strip()
    segment = request.args.get('segment', '').strip()
    seller_id = request.args.get('seller_id', '').strip()
    store_id = request.args.get('store_id', '').strip()
    tier = request.args.get('tier', '').strip()
    source = request.args.get('source', '').strip()
    badge = request.args.get('badge', '').strip()
    bot_mode = request.args.get('bot_mode', '').strip()

    query = Client.query

    if q:
        query = query.filter(or_(
            Client.name.ilike(f'%{q}%'),
            Client.phone.ilike(f'%{q}%'),
            Client.email.ilike(f'%{q}%'),
            Client.cpf.ilike(f'%{q}%'),
            Client.segment.ilike(f'%{q}%'),
            Client.category.ilike(f'%{q}%'),
            Client.notes.ilike(f'%{q}%'),
            Client.website.ilike(f'%{q}%'),
            Client.instagram.ilike(f'%{q}%')
        ))

    if segment:
        query = query.filter(or_(Client.segment == segment, Client.category == segment))

    if seller_id:
        try:
            sid = int(seller_id)
            query = query.filter(or_(Client.assigned_to == sid, Client.referred_by_id == sid))
        except ValueError:
            pass

    if store_id:
        try:
            stid = int(store_id)
            query = query.filter(Client.preferred_store_id == stid)
        except ValueError:
            pass

    if tier:
        query = query.filter(Client.tier == tier)

    if source:
        if source == 'gmaps':
            query = query.filter(Client.badges.ilike('%outbound_gmaps%'))
        else:
            query = query.filter(Client.lead_source == source)

    if badge:
        query = query.filter(Client.badges.contains(badge))

    if bot_mode == 'robo':
        query = query.filter(Client.bot_enabled.is_(True))
    elif bot_mode == 'humano':
        query = query.filter(Client.bot_enabled.is_(False))

    all_clients = query.order_by(Client.updated_at.desc()).all()
    clients_by_status = defaultdict(list)
    for c in all_clients:
        clients_by_status[c.status].append(c)

    # Segmentos e usuários para os filtros
    segments_raw = db.session.query(Client.segment).filter(Client.segment.isnot(None), Client.segment != '').distinct().all()
    categories_raw = db.session.query(Client.category).filter(Client.category.isnot(None), Client.category != '').distinct().all()
    all_segments = sorted(list(set([s[0].strip() for s in segments_raw + categories_raw if s[0] and s[0].strip()])))

    users = User.query.order_by(User.username).all()
    stores = Store.query.order_by(Store.name).all()

    current_filters = {
        'q': q,
        'segment': segment,
        'seller_id': seller_id,
        'store_id': store_id,
        'tier': tier,
        'source': source,
        'badge': badge,
        'bot_mode': bot_mode
    }
    has_active_filters = bool(q or segment or seller_id or store_id or tier or source or badge or bot_mode)

    settings = {s.key: s.value for s in Setting.query.all()}
    total_db_clients = Client.query.count()

    return render_template(
        'crm/kanban.html',
        title='Funil de Vendas',
        clients_by_status=clients_by_status,
        total_clients=len(all_clients),
        total_db_clients=total_db_clients,
        all_segments=all_segments,
        users=users,
        stores=stores,
        settings=settings,
        current_filters=current_filters,
        has_active_filters=has_active_filters,
        active_badge=badge
    )


# ── Move card via drag-and-drop (AJAX) ───────────────────────────────────────
@bp.route('/client/<int:id>/move', methods=['POST'])
@login_required
def move_client(id):
    client = Client.query.get_or_404(id)
    data   = request.get_json(force=True)
    new_status = data.get('status')

    valid_statuses = ['lead', 'contato', 'proposta', 'fechado', 'perdido']
    if new_status not in valid_statuses:
        return jsonify({'ok': False, 'error': 'Invalid status'}), 400

    old_status = client.status
    client.status = new_status

    # Log & XP
    log = SystemLog(user_id=current_user.id,
                    action=f"Moveu {client.name}: {old_status} → {new_status}")
    db.session.add(log)

    if new_status == 'fechado' and old_status != 'fechado':
        award_xp(current_user, XP_FECHAR_VENDA, f"Venda fechada com {client.name}")
    elif new_status == 'proposta' and old_status == 'lead':
        award_xp(current_user, XP_LEAD_PROPOSTA, f"Proposta enviada para {client.name}")
    elif new_status != old_status:
        award_xp(current_user, XP_STATUS_MOVE, f"Atualizou {client.name} para {new_status}")

    db.session.commit()
    return jsonify({'ok': True})


# ── New client ────────────────────────────────────────────────────────────────
@bp.route('/client/new', methods=['GET', 'POST'])
@login_required
def new_client():
    if request.method == 'POST':
        phone = request.form.get('phone')
        cpf = request.form.get('cpf') or None
        segment = (request.form.get('segment') or '').strip() or None
        instagram = (request.form.get('instagram') or '').strip() or None
        website = (request.form.get('website') or '').strip() or None
        
        # Unique validations
        if Client.query.filter_by(phone=phone).first():
            flash('⚠️ Este número de celular já está cadastrado em outro cliente.', 'error')
            return redirect(request.url)
            
        if cpf and Client.query.filter_by(cpf=cpf).first():
            flash('⚠️ Este CPF/CNPJ já está cadastrado.', 'error')
            return redirect(request.url)

        client = Client(
            # Essencial
            name=request.form.get('name'),
            cpf=cpf, # Salva None se vazio
            phone=phone,
            email=request.form.get('email') or None,
            cep=request.form.get('cep') or None,
            address=request.form.get('address') or None,
            birth_date=datetime.strptime(request.form.get('birth_date'), '%Y-%m-%d').date() if request.form.get('birth_date') else None,
            status=request.form.get('status', 'lead'),
            notes=request.form.get('notes'),
            assigned_to=current_user.id,
            
            # Presença Digital e Segmento
            segment=segment,
            category=segment,
            instagram=instagram,
            website=website,

            # Estratégico
            gender=request.form.get('gender'),
            preferred_store_id=request.form.get('preferred_store_id') or None,
            referred_by_id=request.form.get('referred_by_id') or None,
            preferred_channel=request.form.get('preferred_channel'),
            lead_source=request.form.get('lead_source'),
            
            # Modo de Atendimento (Robô vs Humano)
            bot_enabled=str(request.form.get('bot_enabled', 'true')).lower() in ['true', '1', 'yes', 'bot', 'robo'],

            # LGPD
            opt_in=True if request.form.get('opt_in') else False,
            opt_in_date=datetime.utcnow() if request.form.get('opt_in') else None,
            consent_channel=request.form.get('consent_channel'),
            data_usage_purpose=request.form.get('data_usage_purpose'),
        )
        db.session.add(client)

        log = SystemLog(user_id=current_user.id,
                        action=f"Cadastrou novo cliente: {client.name}")
        db.session.add(log)

        award_xp(current_user, XP_NOVO_CLIENTE, f"Novo cliente cadastrado: {client.name}")

        db.session.commit()
        try:
            EventBus.publish('client.created', client)
        except Exception as e:
            pass
        flash('✅ Cliente cadastrado com sucesso!')
        return redirect(url_for('crm.list_clients'))

    users = User.query.all()
    stores = Store.query.all()
    return render_template('crm/form.html', title='Novo Cliente', users=users, stores=stores)


# ── Edit client ───────────────────────────────────────────────────────────────
@bp.route('/client/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_client(id):
    client = Client.query.get_or_404(id)
    if request.method == 'POST':
        new_phone = request.form.get('phone')
        new_cpf = request.form.get('cpf') or None
        new_segment = (request.form.get('segment') or '').strip() or None
        new_instagram = (request.form.get('instagram') or '').strip() or None
        new_website = (request.form.get('website') or '').strip() or None

        # Verify Uniqueness
        if new_phone != client.phone and Client.query.filter_by(phone=new_phone).first():
            flash('⚠️ Este número de celular já está vinculado a outro cadastro.', 'error')
            return redirect(request.url)
        
        if new_cpf and new_cpf != client.cpf and Client.query.filter_by(cpf=new_cpf).first():
            flash('⚠️ Este CPF/CNPJ já está registrado em outro cliente.', 'error')
            return redirect(request.url)

        old_status = client.status
        client.name  = request.form.get('name')
        client.cpf   = new_cpf
        client.phone = new_phone
        client.email = request.form.get('email')
        client.cep   = request.form.get('cep')
        client.address = request.form.get('address')
        client.notes = request.form.get('notes')
        client.segment = new_segment
        client.category = new_segment
        client.instagram = new_instagram
        client.website = new_website
        if request.form.get('birth_date'):
            client.birth_date = datetime.strptime(request.form.get('birth_date'), '%Y-%m-%d').date()
        else:
            client.birth_date = None
        
        client.gender = request.form.get('gender')
        client.preferred_store_id = request.form.get('preferred_store_id') or None
        client.referred_by_id = request.form.get('referred_by_id') or None
        client.preferred_channel = request.form.get('preferred_channel')
        client.lead_source = request.form.get('lead_source')

        # Modo de Atendimento (Robô vs Humano)
        if 'bot_enabled' in request.form:
            bot_enabled_raw = request.form.get('bot_enabled')
            client.bot_enabled = str(bot_enabled_raw).lower() in ['true', '1', 'yes', 'bot', 'robo']
            if client.phone:
                try:
                    from app.utils.lead_enricher import LeadEnricher
                    clean_phone = LeadEnricher.clean_digits(client.phone)
                    from app.utils.dialogue_collector import DialogueCollector
                    if not client.bot_enabled:
                        DialogueCollector.activate_human_takeover(clean_phone or client.phone, reason="chave_humano_crm")
                    else:
                        DialogueCollector.deactivate_human_takeover(clean_phone or client.phone)
                except Exception:
                    pass
        
        client.opt_in = True if request.form.get('opt_in') else False
        client.consent_channel = request.form.get('consent_channel')
        client.data_usage_purpose = request.form.get('data_usage_purpose')

        new_status = request.form.get('status')
        if new_status != old_status:
            client.status = new_status
            if new_status == 'fechado':
                award_xp(current_user, XP_FECHAR_VENDA, f"Venda fechada com {client.name}")
            elif new_status == 'proposta' and old_status == 'lead':
                award_xp(current_user, XP_LEAD_PROPOSTA, f"Proposta para {client.name}")
        else:
            client.status = new_status

        log = SystemLog(user_id=current_user.id,
                        action=f"Editou cliente: {client.name}")
        db.session.add(log)
        db.session.commit()
        flash('✅ Cliente atualizado com sucesso!')
        return redirect(url_for('crm.list_clients'))

    users = User.query.all()
    stores = Store.query.all()
    tf_profile = None
    try:
        from app.utils.tf_engine import TensorFlowEngine
        tf_profile = TensorFlowEngine.get_client_intelligence_profile(client) if client else None
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[edit_client] Aviso ao carregar perfil preditivo TensorFlow: {e}")
        tf_profile = None

    return render_template('crm/form.html', title='Editar Cliente', client=client, users=users, stores=stores, tf_profile=tf_profile)


# ── Toggle Bot Mode (Robô vs Humano) ──────────────────────────────────────────
@bp.route('/client/<int:id>/toggle-bot', methods=['POST'])
@login_required
def toggle_client_bot(id):
    """Alterna ou define o modo de atendimento do lead (Robô vs Humano)."""
    client = Client.query.get_or_404(id)
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    
    if 'bot_enabled' in data:
        new_val = str(data['bot_enabled']).lower() in ['true', '1', 'yes', 'bot', 'robo']
    else:
        new_val = not client.bot_enabled

    client.bot_enabled = new_val
    db.session.commit()

    if client.phone:
        try:
            from app.utils.lead_enricher import LeadEnricher
            clean_phone = LeadEnricher.clean_digits(client.phone)
            from app.utils.dialogue_collector import DialogueCollector
            if not client.bot_enabled:
                DialogueCollector.activate_human_takeover(clean_phone or client.phone, reason="chave_humano_crm")
            else:
                DialogueCollector.deactivate_human_takeover(clean_phone or client.phone)
        except Exception:
            pass

    mode = "robo" if client.bot_enabled else "humano"
    msg = f"Modo alterado para {'Robô (Respostas automáticas de IA ativas)' if client.bot_enabled else 'Atendimento Humano (Respostas automáticas do bot desativadas)'}."
    
    log = SystemLog(user_id=current_user.id, action=f"Alterou modo de atendimento de '{client.name}' para {mode.upper()}")
    db.session.add(log)
    db.session.commit()

    return jsonify({
        'success': True,
        'client_id': client.id,
        'bot_enabled': client.bot_enabled,
        'mode': mode,
        'label': 'Robô' if client.bot_enabled else 'Humano',
        'message': msg
    })

# ── Message Client (Manual WA / API preview) ──────────────────────────────────
@bp.route('/client/<int:id>/message', methods=['GET', 'POST'])
@login_required
def message_client(id):
    client = Client.query.get_or_404(id)
    if request.method == 'POST':
        text = request.form.get('final_text')
        from app.utils.lead_enricher import LeadEnricher
        wa_url = LeadEnricher.to_whatsapp_url(client.phone, text=text)
        if not wa_url:
            flash('⚠️ Telefone do cliente não possui um número de WhatsApp válido cadastrado.', 'warning')
            return redirect(url_for('crm.list_clients'))
        
        # Log it
        log = MessageLog(
            client_id=client.id,
            user_id=current_user.id,
            content=text,
            channel='whatsapp_link',
            status='sent'
        )
        db.session.add(log)
        
        award_xp(current_user, 2, f"Envio WA para {client.name}")
        db.session.commit()

        # We redirect to the WA url. The user browser will open WA app/web.
        return redirect(wa_url)

    templates = MessageTemplate.query.all()
    interpolated_templates = []
    for t in templates:
        interpolated_templates.append({
            'id': t.id,
            'name': t.name,
            'text': WhatsAppEngine.interpolate(t.text_content, client, current_user)
        })
        
    return render_template('crm/message_form.html', title='Enviar Mensagem', client=client, templates=interpolated_templates)

# ── Delete client ─────────────────────────────────────────────────────────────
@bp.route('/client/<int:id>/delete', methods=['POST'])
@login_required
def delete_client(id):
    client = Client.query.get_or_404(id)
    name = client.name
    db.session.delete(client)

    log = SystemLog(user_id=current_user.id, action=f"Excluiu cliente: {name}")
    db.session.add(log)
    db.session.commit()

    flash(f'🗑️ {name} foi excluído.')
    return redirect(url_for('crm.list_clients'))


# ── CSV Import ────────────────────────────────────────────────────────────────
import csv, io

@bp.route('/import-csv', methods=['GET'])
@login_required
def import_csv():
    return render_template('crm/import.html', title='Importar Clientes')

@bp.route('/client/import_batch', methods=['POST'])
@login_required
def import_batch():
    data = request.json
    if not data or not isinstance(data, list):
        return jsonify({'ok': False, 'error': 'Dados inválidos'}), 400
        
    count = 0
    from app.utils.encoding import sanitize_encoding

    from app.utils.lead_enricher import LeadEnricher

    for row in data:
        raw_name = sanitize_encoding(row.get('name'))
        raw_phone = str(row.get('phone', '')).strip()
        phone_formatted = LeadEnricher.format_phone_display(raw_phone) if raw_phone else ''
        phone_to_save = phone_formatted or LeadEnricher.clean_digits(raw_phone)

        if raw_name and phone_to_save:
            existing = LeadEnricher.find_client_by_phone(phone_to_save)
            if not existing:
                segment_val = sanitize_encoding((row.get('segment') or row.get('category') or '').strip()) or None
                website_val = (row.get('website') or '').strip() or None
                instagram_val = (row.get('instagram') or '').strip() or None
                address_val = sanitize_encoding(row.get('address')) or None
                if website_val and 'instagram.com' in website_val.lower() and not instagram_val:
                    instagram_val = website_val

                db.session.add(Client(
                    name=raw_name,
                    phone=phone_to_save,
                    email=row.get('email') or None,
                    cpf=row.get('cpf') or None,
                    address=address_val,
                    segment=segment_val,
                    category=segment_val,
                    website=website_val,
                    instagram=instagram_val,
                    status='lead',
                    assigned_to=current_user.id
                ))
                count += 1
                
    if count > 0:
        xp_gain = count * 5
        award_xp(current_user, xp_gain, f"Importou {count} clientes")
        log = SystemLog(user_id=current_user.id, action=f"Importou {count} clientes")
        db.session.add(log)
        db.session.commit()
        
    return jsonify({'ok': True, 'count': count})

def build_client_filter_query(filters: dict):
    """Constrói consulta refinada de leads com base em critérios multi-dimensionais."""
    query = Client.query.filter(Client.phone.isnot(None), Client.phone != '')
    if not filters:
        return query

    # 1. Filtro de Status
    statuses = filters.get('statuses')
    if statuses and isinstance(statuses, list) and len(statuses) > 0 and 'all' not in statuses:
        query = query.filter(Client.status.in_(statuses))
    elif isinstance(statuses, str) and statuses and statuses != 'all':
        query = query.filter(Client.status == statuses)

    # 2. Filtro de Segmento / Categoria (Multi-seleção com fallback retrocompatível)
    segments = filters.get('segments') if filters.get('segments') is not None else filters.get('segment')
    if segments:
        if isinstance(segments, str):
            if ',' in segments:
                segments = [s.strip() for s in segments.split(',') if s.strip()]
            elif segments != 'all':
                segments = [segments]
            else:
                segments = []
        if isinstance(segments, list) and len(segments) > 0 and 'all' not in segments:
            query = query.filter(or_(Client.segment.in_(segments), Client.category.in_(segments)))

    # 3. Filtro de Origem do Lead
    sources = filters.get('sources')
    if sources and isinstance(sources, list) and len(sources) > 0 and 'all' not in sources:
        query = query.filter(Client.lead_source.in_(sources))
    elif isinstance(sources, str) and sources and sources != 'all':
        query = query.filter(Client.lead_source == sources)

    # 4. Filtro de Vendedor / Responsável
    assigned_to = filters.get('assigned_to')
    if assigned_to and assigned_to != 'all':
        if assigned_to == 'unassigned':
            query = query.filter(Client.assigned_to.is_(None))
        else:
            try:
                query = query.filter(Client.assigned_to == int(assigned_to))
            except (ValueError, TypeError):
                pass

    # 5. Filtro de DDDs
    ddds = filters.get('ddds')
    if ddds and isinstance(ddds, list) and len(ddds) > 0:
        clean_ddds = [str(d).strip() for d in ddds if str(d).strip().isdigit()]
        if clean_ddds:
            ddd_conditions = [Client.phone.ilike(f'%{d}%') for d in clean_ddds]
            query = query.filter(or_(*ddd_conditions))

    # 6. Filtro Anti-Fadiga (descarta contatados recentemente)
    anti_fatigue_days = filters.get('anti_fatigue_days')
    if anti_fatigue_days:
        try:
            days = int(anti_fatigue_days)
            if days > 0:
                cutoff = datetime.utcnow() - timedelta(days=days)
                recent_ids = db.session.query(MessageLog.client_id).filter(
                    MessageLog.timestamp >= cutoff,
                    MessageLog.client_id.isnot(None)
                ).scalar_subquery()
                query = query.filter(Client.id.not_in(recent_ids))
        except (ValueError, TypeError):
            pass

    # 7. Conformidade LGPD (apenas com Opt-in)
    if filters.get('opt_in_only'):
        query = query.filter(Client.opt_in.is_(True))

    return query


# ── Bulk Message Engine (Painel & Controle Desacoplado) ───────────────────────
@bp.route('/bulk-message', methods=['GET'])
@login_required
@requires_module('waha_bulk')
def bulk_message():
    templates = MessageTemplate.query.order_by(MessageTemplate.name.asc()).all()
    templates_data = [{'id': t.id, 'name': t.name, 'text': t.text_content} for t in templates]
    
    # Instâncias WAHA
    waha_instances = WahaInstance.query.order_by(WahaInstance.id).all()
    waha_instances_stats = {inst.id: inst.get_anti_ban_stats() for inst in waha_instances}
    
    # Extração de Metadados Únicos para os Filtros Avançados
    segments_raw = db.session.query(Client.segment).filter(Client.segment.isnot(None), Client.segment != '').distinct().all()
    categories_raw = db.session.query(Client.category).filter(Client.category.isnot(None), Client.category != '').distinct().all()
    all_segments = sorted(list(set([s[0].strip() for s in segments_raw if s[0]] + [c[0].strip() for c in categories_raw if c[0]])))

    sources_raw = db.session.query(Client.lead_source).filter(Client.lead_source.isnot(None), Client.lead_source != '').distinct().all()
    all_sources = sorted(list(set([s[0].strip() for s in sources_raw if s[0]])))

    assigned_users = User.query.filter_by(is_active=True).order_by(User.username.asc()).all()

    # Campanhas Recentes e Campanha Ativa
    recent_campaigns = BulkCampaign.query.order_by(BulkCampaign.id.desc()).limit(15).all()
    active_campaign = BulkCampaign.query.filter(BulkCampaign.status.in_(['running', 'paused'])).order_by(BulkCampaign.id.desc()).first()

    # Total geral de clientes com telefone cadastrado
    total_clients_with_phone = Client.query.filter(Client.phone.isnot(None), Client.phone != '').count()

    # Histórico de envios de mensagens
    logs = MessageLog.query.order_by(MessageLog.timestamp.desc()).limit(100).all()
    active_tab = request.args.get('tab', 'disparo')

    return render_template('crm/bulk_message.html', 
                           title='Disparo em Lote Inteligente (WAHA)', 
                           templates=templates_data,
                           waha_instances=waha_instances,
                           waha_instances_stats=waha_instances_stats,
                           segments=all_segments,
                           lead_sources=all_sources,
                           assigned_users=assigned_users,
                           total_clients_count=total_clients_with_phone,
                           recent_campaigns=[c.to_dict() for c in recent_campaigns],
                           active_campaign=active_campaign.to_dict() if active_campaign else None,
                           master_switch_enabled=is_master_switch_enabled(),
                           logs=logs,
                           active_tab=active_tab)


# ── APIs do Motor Desacoplado e Filtragem ─────────────────────────────────────

@bp.route('/api/bulk/estimate', methods=['POST'])
@login_required
def api_bulk_estimate():
    """Calcula quantidade e retorna amostra de leads com base no filtro multi-critério."""
    data = request.get_json(force=True) or {}
    query = build_client_filter_query(data)
    count = query.count()
    
    # Amostra de 5 contatos para conferência visual
    sample_leads = query.limit(5).all()
    sample_data = [{'name': c.name, 'phone': c.phone, 'status': c.status, 'segment': c.display_segment} for c in sample_leads]

    return jsonify({
        'ok': True,
        'count': count,
        'sample': sample_data
    })


@bp.route('/api/bulk/campaigns', methods=['POST'])
@login_required
def api_bulk_create_campaign():
    """Cria uma nova campanha e compila sua fila no banco de dados com desduplicação."""
    data = request.get_json(force=True) or {}
    
    name = (data.get('name') or f"Campanha {datetime.now().strftime('%d/%m %H:%M')}").strip()
    message_text = (data.get('message_text') or '').strip()
    if not message_text:
        return jsonify({'ok': False, 'error': 'O texto da mensagem é obrigatório'}), 400

    waha_instance_id = data.get('waha_instance_id')
    template_id = data.get('template_id')
    min_delay = int(data.get('min_delay', 6))
    max_delay = int(data.get('max_delay', 16))
    use_ai = bool(data.get('use_ai', False))
    use_spintax = bool(data.get('use_spintax', True))
    batch_pause_every = int(data.get('batch_pause_every', 25))
    batch_pause_duration = int(data.get('batch_pause_duration', 60))

    # Criação do Registro da Campanha
    campaign = BulkCampaign(
        name=name,
        status='draft',
        message_text=message_text,
        waha_instance_id=int(waha_instance_id) if waha_instance_id else None,
        created_by_id=current_user.id,
        template_id=int(template_id) if template_id else None,
        min_delay=min_delay,
        max_delay=max_delay,
        batch_pause_every=batch_pause_every,
        batch_pause_duration=batch_pause_duration,
        use_ai=use_ai,
        use_spintax=use_spintax
    )
    db.session.add(campaign)
    db.session.flush() # obtém campaign.id

    recipients_to_insert = []
    seen_phones = set()

    # 1. Coleta Destinatários do Filtro CRM
    filters = data.get('filters')
    if filters and (filters.get('apply_crm') or filters.get('statuses') or filters.get('segments')):
        crm_query = build_client_filter_query(filters)
        clients = crm_query.all()
        for c in clients:
            clean = ''.join(filter(str.isdigit, str(c.phone or '')))
            if len(clean) >= 10 and clean not in seen_phones:
                seen_phones.add(clean)
                recipients_to_insert.append(BulkCampaignRecipient(
                    campaign_id=campaign.id,
                    client_id=c.id,
                    name=c.name or 'Cliente',
                    phone=clean,
                    source='crm',
                    status='pending'
                ))

    # 2. Coleta Destinatários da Lista Manual
    manual_list = data.get('manual_list', '').strip()
    if manual_list:
        for line in manual_list.split('\n'):
            line = line.strip()
            if not line:
                continue
            parts = line.split(',')
            m_name = parts[0].strip() if len(parts) >= 2 else 'Contato'
            raw_phone = parts[1].strip() if len(parts) >= 2 else parts[0].strip()
            clean = ''.join(filter(str.isdigit, raw_phone))
            if len(clean) >= 10 and clean not in seen_phones:
                seen_phones.add(clean)
                recipients_to_insert.append(BulkCampaignRecipient(
                    campaign_id=campaign.id,
                    client_id=None,
                    name=m_name,
                    phone=clean,
                    source='manual',
                    status='pending'
                ))

    # 3. Coleta Destinatários de Planilha Importada
    imported_clients = data.get('imported_clients', [])
    if imported_clients and isinstance(imported_clients, list):
        for item in imported_clients:
            i_name = (item.get('name') or 'Contato').strip()
            raw_phone = str(item.get('phone') or '')
            clean = ''.join(filter(str.isdigit, raw_phone))
            if len(clean) >= 10 and clean not in seen_phones:
                seen_phones.add(clean)
                recipients_to_insert.append(BulkCampaignRecipient(
                    campaign_id=campaign.id,
                    client_id=None,
                    name=i_name,
                    phone=clean,
                    source='file',
                    status='pending'
                ))

    if not recipients_to_insert:
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'Nenhum contato válido encontrado para inclusão na fila.'}), 400

    campaign.total_count = len(recipients_to_insert)
    db.session.bulk_save_objects(recipients_to_insert)
    db.session.commit()

    return jsonify({
        'ok': True,
        'message': f'Fila compilada com sucesso com {campaign.total_count} contatos únicos!',
        'campaign': campaign.to_dict()
    })


@bp.route('/api/bulk/campaigns/<int:id>/start', methods=['POST'])
@login_required
def api_bulk_campaign_start(id):
    """Inicia ou retoma uma campanha no motor desacoplado."""
    success, message = start_campaign_engine(id)
    return jsonify({'ok': success, 'message': message}), (200 if success else 400)


@bp.route('/api/bulk/campaigns/<int:id>/pause', methods=['POST'])
@login_required
def api_bulk_campaign_pause(id):
    """Pausa a execução de uma campanha em andamento."""
    success, message = pause_campaign_engine(id, reason="Pausado pelo usuário na interface")
    return jsonify({'ok': success, 'message': message})


@bp.route('/api/bulk/campaigns/<int:id>/cancel', methods=['POST'])
@login_required
def api_bulk_campaign_cancel(id):
    """Cancela a campanha e desativa os envios pendentes."""
    success, message = cancel_campaign_engine(id)
    return jsonify({'ok': success, 'message': message})


@bp.route('/api/bulk/campaigns/<int:id>/status', methods=['GET'])
@login_required
def api_bulk_campaign_status(id):
    """Retorna telemetria em tempo real, status da fila e métricas anti-ban."""
    campaign = BulkCampaign.query.get_or_404(id)
    telemetry = get_campaign_telemetry(id)
    
    inst = campaign.waha_instance
    inst_stats = inst.get_anti_ban_stats() if inst else None

    return jsonify({
        'ok': True,
        'campaign': campaign.to_dict(),
        'speed_mpm': telemetry.get('speed_mpm', 0.0),
        'eta_seconds': telemetry.get('eta_seconds', 0),
        'logs': telemetry.get('logs', []),
        'master_switch_enabled': is_master_switch_enabled(),
        'instance_stats': inst_stats
    })


@bp.route('/api/bulk/master-switch', methods=['POST'])
@login_required
def api_bulk_toggle_master_switch():
    """Liga ou desliga o Master Switch global do motor de disparo."""
    data = request.get_json(force=True) or {}
    enabled = bool(data.get('enabled', True))
    set_master_switch(enabled)
    return jsonify({'ok': True, 'master_switch_enabled': enabled})


@bp.route('/api/bulk/spintax-preview', methods=['POST'])
@login_required
def api_bulk_spintax_preview():
    """Gera 3 variações dinâmicas de exemplo usando Spintax e variáveis de teste."""
    data = request.get_json(force=True) or {}
    text = data.get('text', '')
    if not text:
        return jsonify({'ok': True, 'variations': []})

    # Mock de contatos de teste
    test_contacts = [
        {'name': 'Lucas Andrade', 'client_name': 'Lucas Andrade', 'status': 'lead', 'segment': 'Tecnologia', 'address': 'São Paulo - SP'},
        {'name': 'Fernanda Lima', 'client_name': 'Fernanda Lima', 'status': 'proposta', 'segment': 'Varejo', 'address': 'Rio de Janeiro - RJ'},
        {'name': 'Carlos Eduardo', 'client_name': 'Carlos Eduardo', 'status': 'contato', 'segment': 'Alimentos', 'address': 'Curitiba - PR'}
    ]

    class MockRecipient:
        def __init__(self, name):
            self.name = name

    class MockClient:
        def __init__(self, name, status, segment, address):
            self.name = name
            self.status = status
            self.segment = segment
            self.display_segment = segment
            self.address = address

    variations = []
    for c in test_contacts:
        rec = MockRecipient(c['name'])
        cli = MockClient(c['client_name'], c['status'], c['segment'], c['address'])
        resolved = resolve_message_variables(text, rec, cli)
        variations.append(resolved)

    return jsonify({'ok': True, 'variations': variations})


@bp.route('/api/external/send', methods=['POST'])
@login_required
def api_external_send():
    data = request.get_json(force=True)
    if not data:
        return jsonify({'ok': False, 'error': 'No data provided'}), 400
        
    phone = data.get('phone')
    text = data.get('text')
    client_id = data.get('client_id')
    source = data.get('source', 'bulk') # crm or manual
    use_ai = data.get('use_ai', False)
    
    if not phone or not text:
        return jsonify({'ok': False, 'error': 'Phone and text are required'}), 400
        
    instance_id = data.get('instance_id')
    instance = None
    if instance_id:
        try:
            instance = WahaInstance.query.get(int(instance_id))
        except (ValueError, TypeError):
            pass
    if not instance:
        instance = WahaInstance.query.filter_by(is_default=True).first() or WahaInstance.query.first()

    # Validação Anti-Ban e Rate Limiting
    if instance and instance.enable_anti_ban:
        can_send, reason, stats = instance.check_anti_ban_limits()
        if not can_send:
            return jsonify({
                'ok': False,
                'error': reason,
                'anti_ban_blocked': True,
                'reason_code': stats.get('reason_code'),
                'stats': stats
            }), 429

    # Reescrita com IA (apenas se solicitado e se não for manual?)
    final_text = text
    ai_error = None
    if use_ai:
        final_text, ai_error = AIHandler.rewrite_message(text)
        if ai_error:
            print(f"Aviso de IA: {ai_error}")

    resolved_instance_id = instance.id if instance else instance_id
    success, response = WahaAPI.send_text(phone, final_text, resolved_instance_id)
    
    if success:
        # Registrar cota anti-ban
        if instance:
            instance.record_message_sent()

        # Lógica de Auto-Cadastro / Atualização
        try:
            # Limpa o telefone para busca (apenas dígitos)
            clean_phone = ''.join(filter(str.isdigit, str(phone)))
            
            client = None
            if client_id:
                client = Client.query.get(int(client_id))
            
            if not client:
                # Tenta buscar pelo telefone se não veio ID
                client = Client.query.filter(Client.phone.contains(clean_phone)).first()

            now_str = datetime.now().strftime('%d/%m/%Y %H:%M')
            note_entry = f"\nContato para regularização [{now_str}]"
            
            if client:
                # Atualiza cliente existente
                client.status = "Regularização financeira"
                client.notes = (client.notes or "") + note_entry
                client.updated_at = datetime.utcnow()
            else:
                # Cria novo cliente (Lead Automático)
                new_name = data.get('name', 'Lead Automático')
                client = Client(
                    name=new_name,
                    phone=phone,
                    status="Regularização financeira",
                    notes=f"Contato para regularização [{now_str}]",
                    assigned_to=current_user.id
                )
                db.session.add(client)
            
            # Registrar nos Logs de Mensagem
            log = MessageLog(
                client_id=client.id if client.id else None,
                user_id=current_user.id,
                content=final_text,
                channel='whatsapp_waha',
                status='sent',
                waha_instance_id=resolved_instance_id
            )
            log.client = client
            db.session.add(log)
            
            # Gamification
            current_user.performance_points += 1
            db.session.commit()
            
        except Exception as e:
            db.session.rollback()
            print("Error in auto-registration:", e)
                
        stats = instance.get_anti_ban_stats() if instance else None
        return jsonify({
            'ok': True, 
            'response': response,
            'final_text': final_text,
            'ai_used': use_ai,
            'stats': stats
        })
    else:
        # Registrar o ERRO no log de mensagens
        try:
            clean_phone = ''.join(filter(str.isdigit, str(phone)))
            client = None
            if client_id:
                client = Client.query.get(int(client_id))
            if not client:
                client = Client.query.filter(Client.phone.contains(clean_phone)).first()

            log = MessageLog(
                client_id=client.id if client else None,
                user_id=current_user.id,
                content=text,
                channel='whatsapp_waha',
                status='error',
                api_response=str(response),
                waha_instance_id=resolved_instance_id
            )
            db.session.add(log)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print("Error logging failed message:", e)

        stats = instance.get_anti_ban_stats() if instance else None
        return jsonify({'ok': False, 'error': response, 'stats': stats}), 400

@bp.route('/api/waha/<int:id>/anti_ban_stats', methods=['GET'])
@login_required
def api_waha_anti_ban_stats(id):
    instance = WahaInstance.query.get_or_404(id)
    return jsonify({'ok': True, 'stats': instance.get_anti_ban_stats()})

@bp.route('/api/waha/<int:id>/reset_counters', methods=['POST'])
@login_required
def api_waha_reset_counters(id):
    instance = WahaInstance.query.get_or_404(id)
    instance.hourly_count = 0
    instance.daily_count = 0
    db.session.commit()
    return jsonify({
        'ok': True,
        'message': f'Contadores da instância "{instance.name}" zerados com sucesso.',
        'stats': instance.get_anti_ban_stats()
    })


# ── Prospecção Ativa (Google Maps Scraper) ──────────────────────────────────
@bp.route('/prospeccao')
@login_required
@requires_module('prospecting')
def prospeccao():
    jobs = ScrapingJob.query.order_by(ScrapingJob.created_at.desc()).limit(100).all()
    scraper_client = MapsScraperClient()
    is_online = scraper_client.is_online()
    total_scraped = sum((j.total_scraped or 0) for j in jobs)
    total_imported = sum((j.total_imported or 0) for j in jobs)
    return render_template(
        'crm/prospeccao.html',
        title='Prospecção Ativa de Leads',
        jobs=jobs,
        is_online=is_online,
        total_scraped=total_scraped,
        total_imported=total_imported
    )

@bp.route('/prospeccao/start', methods=['POST'])
@login_required
@requires_module('prospecting')
def prospeccao_start():
    data = request.get_json(silent=True) or request.form.to_dict()
    query = (data.get('query') or data.get('keyword') or '').strip()
    depth = int(data.get('depth') or 1)
    extract_emails = str(data.get('extract_emails', 'true')).lower() in ('true', '1', 'on', 'yes')

    if not query:
        if request.is_json:
            return jsonify({'ok': False, 'error': 'Informe o termo de pesquisa.'}), 400
        flash('⚠️ Informe o termo de pesquisa para a prospecção.', 'warning')
        return redirect(url_for('crm.prospeccao'))

    # Cria o registro do ScrapingJob
    job = ScrapingJob(
        query=query,
        depth=depth,
        extract_emails=extract_emails,
        status='queued',
        created_by_user_id=current_user.id
    )
    db.session.add(job)
    db.session.commit()

    # Dispara processamento em background (RQ ou thread com app context)
    dispatch_scraping_job(job.id)

    if request.is_json:
        return jsonify({
            'ok': True,
            'message': 'Busca agendada com sucesso!',
            'job': job.to_dict()
        })

    flash(f'🚀 Prospecção iniciada para "{query}". Os novos leads serão importados automaticamente.', 'success')
    return redirect(url_for('crm.prospeccao'))

@bp.route('/prospeccao/job/<int:id>/status', methods=['GET'])
@login_required
def prospeccao_job_status(id):
    job = ScrapingJob.query.get_or_404(id)
    return jsonify({'ok': True, 'job': job.to_dict()})

@bp.route('/prospeccao/jobs/active', methods=['GET'])
@login_required
def prospeccao_active_jobs():
    active_jobs = ScrapingJob.query.filter(ScrapingJob.status.in_(['queued', 'processing'])).all()
    return jsonify({'ok': True, 'jobs': [j.to_dict() for j in active_jobs]})


@bp.route('/prospeccao/job/<int:id>/cancel', methods=['POST'])
@login_required
def prospeccao_job_cancel(id):
    from app.tasks.lead_scraper import cancel_scraping_job
    job = ScrapingJob.query.get_or_404(id)
    success, message = cancel_scraping_job(job.id)

    db.session.refresh(job)

    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'ok': success,
            'message': message,
            'job': job.to_dict()
        }), (200 if success else 400)

    flash(message, 'success' if success else 'warning')
    return redirect(url_for('crm.prospeccao'))


