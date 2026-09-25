from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.crm import bp
from collections import defaultdict
from datetime import datetime, timedelta
from sqlalchemy import or_, and_

import urllib.parse
from app.models import Client, SystemLog, Setting, User, Store, MessageTemplate, MessageLog, WahaInstance, ScrapingJob
from app.utils.messaging import WhatsAppEngine
from app.utils.waha import WahaAPI
from app.utils.ai_handler import AIHandler
from app.utils.maps_scraper import MapsScraperClient
from app.tasks.lead_scraper import dispatch_scraping_job
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
        'badge': badge
    }
    has_active_filters = bool(q or segment or seller_id or store_id or tier or source or badge)

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
    return render_template('crm/form.html', title='Editar Cliente', client=client, users=users, stores=stores)

# ── Message Client (Manual WA / API preview) ──────────────────────────────────
@bp.route('/client/<int:id>/message', methods=['GET', 'POST'])
@login_required
def message_client(id):
    client = Client.query.get_or_404(id)
    if request.method == 'POST':
        text = request.form.get('final_text')
        phone = ''.join(filter(str.isdigit, str(client.phone)))
        
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

        wa_url = f"https://wa.me/55{phone}?text={urllib.parse.quote(text.encode('utf-8'))}"
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

    for row in data:
        raw_name = sanitize_encoding(row.get('name'))
        phone = ''.join(filter(str.isdigit, str(row.get('phone', ''))))
        if raw_name and phone:
            existing = Client.query.filter_by(phone=phone).first()
            if not existing:
                segment_val = sanitize_encoding((row.get('segment') or row.get('category') or '').strip()) or None
                website_val = (row.get('website') or '').strip() or None
                instagram_val = (row.get('instagram') or '').strip() or None
                address_val = sanitize_encoding(row.get('address')) or None
                if website_val and 'instagram.com' in website_val.lower() and not instagram_val:
                    instagram_val = website_val

                db.session.add(Client(
                    name=raw_name,
                    phone=phone,
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

# ── Bulk Message Engine ────────────────────────────────────────────────────────
@bp.route('/bulk-message', methods=['GET'])
@login_required
def bulk_message():
    templates = MessageTemplate.query.all()
    # Listamos todos os clientes ativos com número de telefone para o usuário filtrar
    clients_raw = Client.query.filter(Client.phone.isnot(None), Client.phone != '').all()
    
    clients = []
    for c in clients_raw:
        clients.append({
            'id': c.id,
            'name': c.name or '',
            'phone': ''.join(filter(str.isdigit, str(c.phone))),
            'status': c.status or ''
        })
        
    templates_data = [{'id': t.id, 'name': t.name, 'text': t.text_content} for t in templates]
    
    # WAHA Instances
    waha_instances = WahaInstance.query.order_by(WahaInstance.id).all()
    waha_instances_stats = {inst.id: inst.get_anti_ban_stats() for inst in waha_instances}
    
    # Busca logs para a aba de histórico
    logs = MessageLog.query.order_by(MessageLog.timestamp.desc()).limit(200).all()
    active_tab = request.args.get('tab', 'disparo')
    
    return render_template('crm/bulk_message.html', 
                           title='Disparo em Lote', 
                           templates=templates_data,
                           clients_json=clients,
                           waha_instances=waha_instances,
                           waha_instances_stats=waha_instances_stats,
                           logs=logs,
                           active_tab=active_tab)

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


