from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.crm import bp
from collections import defaultdict
from datetime import datetime

import urllib.parse
from app.models import Client, SystemLog, Setting, User, Store, MessageTemplate, MessageLog, WahaInstance
from app.utils.messaging import WhatsAppEngine
from app.utils.waha import WahaAPI
from app.utils.ai_handler import AIHandler
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
    clients = Client.query.order_by(Client.updated_at.desc()).all()
    return render_template('crm/list.html', title='Lista de Clientes', clients=clients)


# ── Kanban board ──────────────────────────────────────────────────────────────
@bp.route('/kanban')
@login_required
def kanban():
    all_clients = Client.query.all()
    clients_by_status = defaultdict(list)
    for c in all_clients:
        clients_by_status[c.status].append(c)

    settings = {s.key: s.value for s in Setting.query.all()}
    return render_template('crm/kanban.html', title='Funil de Vendas',
                           clients_by_status=clients_by_status,
                           total_clients=len(all_clients),
                           settings=settings)


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
        
        # Unique validations
        if Client.query.filter_by(phone=phone).first():
            flash('⚠️ Este número de celular já está cadastrado em outro cliente.', 'error')
            return redirect(request.url)
            
        if cpf and Client.query.filter_by(cpf=cpf).first():
            flash('⚠️ Este CPF já está cadastrado.', 'error')
            return redirect(request.url)

        client = Client(
            # Essencial
            name=request.form.get('name'),
            cpf=request.form.get('cpf') or None, # Salva None se vazio
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            cep=request.form.get('cep'),
            address=request.form.get('address'),
            birth_date=datetime.strptime(request.form.get('birth_date'), '%Y-%m-%d').date() if request.form.get('birth_date') else None,
            status=request.form.get('status', 'lead'),
            notes=request.form.get('notes'),
            assigned_to=current_user.id,
            
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

        # Verify Uniqueness
        if new_phone != client.phone and Client.query.filter_by(phone=new_phone).first():
            flash('⚠️ Este número de celular já está vinculado a outro cadastro.', 'error')
            return redirect(request.url)
        
        if new_cpf and new_cpf != client.cpf and Client.query.filter_by(cpf=new_cpf).first():
            flash('⚠️ Este CPF já está registrado em outro cliente.', 'error')
            return redirect(request.url)

        old_status = client.status
        client.name  = request.form.get('name')
        client.cpf   = new_cpf
        client.phone = new_phone
        client.email = request.form.get('email')
        client.cep   = request.form.get('cep')
        client.address = request.form.get('address')
        client.notes = request.form.get('notes')
        if request.form.get('birth_date'):
            client.birth_date = datetime.strptime(request.form.get('birth_date'), '%Y-%m-%d').date()
        
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
    for row in data:
        phone = ''.join(filter(str.isdigit, str(row.get('phone', ''))))
        if row.get('name') and phone:
            existing = Client.query.filter_by(phone=phone).first()
            if not existing:
                db.session.add(Client(
                    name=row.get('name'),
                    phone=phone,
                    email=row.get('email'),
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
    
    # Busca logs para a aba de histórico
    logs = MessageLog.query.order_by(MessageLog.timestamp.desc()).limit(200).all()
    active_tab = request.args.get('tab', 'disparo')
    
    return render_template('crm/bulk_message.html', 
                           title='Disparo em Lote', 
                           templates=templates_data,
                           clients_json=clients,
                           waha_instances=waha_instances,
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
        
    # Reescrita com IA (apenas se solicitado e se não for manual?)
    # Geralmente fazemos na mensagem base já interpolada
    final_text = text
    ai_error = None
    if use_ai:
        final_text, ai_error = AIHandler.rewrite_message(text)
        if ai_error:
            print(f"Aviso de IA: {ai_error}")

    instance_id = data.get('instance_id')
    success, response = WahaAPI.send_text(phone, final_text, instance_id)
    
    if success:
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
                waha_instance_id=instance_id
            )
            # Se for novo cliente, o ID só existirá após o flush/commit
            # Mas podemos associar o objeto diretamente se o SQLAlchemy permitir
            log.client = client
            db.session.add(log)
            
            # Gamification
            current_user.performance_points += 1
            db.session.commit()
            
        except Exception as e:
            db.session.rollback()
            print("Error in auto-registration:", e)
                
        return jsonify({
            'ok': True, 
            'response': response,
            'final_text': final_text,
            'ai_used': use_ai
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
                waha_instance_id=instance_id
            )
            db.session.add(log)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print("Error logging failed message:", e)

        return jsonify({'ok': False, 'error': response}), 400
