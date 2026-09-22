from flask import render_template, redirect, url_for, flash, request, jsonify, current_app, send_file
from flask_login import login_required, current_user
from app import db
from app.admin import bp
from app.models import Setting, User, SystemLog, Client, Store, MessageTemplate, MessageLog, WahaInstance
from app.utils.waha import WahaAPI
from app.utils.exports import ReportGenerator
from app.utils.ai_handler import AIHandler
import os
import io
from datetime import datetime
from functools import wraps

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.role not in ['admin', 'gerente']:
            flash('Você não tem permissão para acessar esta página.')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function

def superadmin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.role != 'admin':
            flash('Apenas administradores podem realizar esta ação.')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function

@bp.route('/api/messages/export', methods=['GET'])
@login_required
@admin_required
def export_messages():
    export_format = request.args.get('format', 'csv')
    logs = MessageLog.query.order_by(MessageLog.timestamp.desc()).all()
    
    if export_format == 'csv':
        csv_data = ReportGenerator.generate_csv(logs)
        return send_file(
            io.BytesIO(csv_data.encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'relatorio_disparos_{datetime.now().strftime("%Y%m%d")}.csv'
        )
    elif export_format == 'pdf':
        pdf_data = ReportGenerator.generate_pdf(logs)
        return send_file(
            io.BytesIO(pdf_data),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'relatorio_disparos_{datetime.now().strftime("%Y%m%d")}.pdf'
        )
    
    return jsonify({'ok': False, 'error': 'Formato inválido'}), 400


# ── Settings ──────────────────────────────────────────────────────────────────
@bp.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    if request.method == 'POST':
        keys = [
            'msg_boas_vindas', 'msg_proposta', 'msg_fechamento', 'frase_bom_dia', 
            'ai_api_key', 'ai_provider', 'ai_system_prompt', 'ai_ollama_url', 'ai_ollama_model'
        ]
        
        # Only process keys that are actually in the submitted form
        for key in keys:
            if key in request.form:
                val = request.form.get(key)
                setting = Setting.query.filter_by(key=key).first()
                if not setting:
                    setting = Setting(key=key, value=val)
                    db.session.add(setting)
                else:
                    setting.value = val
                    
        db.session.commit()
        
        tab_param = request.args.get('tab', '')
        flash('✅ Configurações atualizadas com sucesso!')
        return redirect(url_for('admin.settings') + (f'?tab={tab_param}' if tab_param else ''))

    all_settings = {s.key: s.value for s in Setting.query.all()}
    stores = Store.query.all()
    waha_instances = WahaInstance.query.order_by(WahaInstance.id).all()
    active_tab = request.args.get('tab', 'templates')
    from app.utils.network import get_connected_ip, resolve_instance_api_url
    detected_ip = get_connected_ip()
    return render_template('admin/settings.html', title='Configurações do Sistema',
                           settings=all_settings, stores=stores, waha_instances=waha_instances,
                           active_tab=active_tab, detected_ip=detected_ip)

@bp.route('/stores/new', methods=['POST'])
@login_required
@admin_required
def new_store():
    name = request.form.get('name', '').strip()
    if name:
        store = Store(name=name)
        db.session.add(store)
        db.session.commit()
        flash(f'✅ Loja "{name}" adicionada com sucesso!')
    return redirect(url_for('admin.settings', tab='stores'))

@bp.route('/stores/<int:id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_store(id):
    store = Store.query.get_or_404(id)
    new_name = request.form.get('name', '').strip()
    if new_name:
        old_name = store.name
        store.name = new_name
        db.session.commit()
        flash(f'✏️ Loja "{old_name}" atualizada para "{new_name}" com sucesso!')
    else:
        flash('O nome da loja não pode ser vazio.', 'warning')
    return redirect(url_for('admin.settings', tab='stores'))

@bp.route('/stores/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_store(id):
    store = Store.query.get_or_404(id)
    name = store.name
    # set preferred_store_id to null for clients that use it
    for client in store.clients:
        client.preferred_store_id = None
    db.session.delete(store)
    db.session.commit()
    flash(f'🗑️ Loja "{name}" removida.')
    return redirect(url_for('admin.settings', tab='stores'))

# ── WAHA Instances ────────────────────────────────────────────────────────────
@bp.route('/waha/new', methods=['POST'])
@login_required
@admin_required
def new_waha_instance():
    from app.utils.network import resolve_instance_api_url
    name = request.form.get('name')
    api_url = resolve_instance_api_url(request.form.get('api_url'))
    api_key = request.form.get('api_key')
    session_name = request.form.get('session_name', 'default')
    
    is_first = WahaInstance.query.count() == 0
    instance = WahaInstance(
        name=name, api_url=api_url, api_key=api_key, 
        session_name=session_name, is_default=is_first
    )
    db.session.add(instance)
    db.session.commit()
    flash(f'✅ Instância WAHA "{name}" adicionada com sucesso!')
    return redirect(url_for('admin.settings', tab='waha'))

@bp.route('/waha/<int:id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_waha_instance(id):
    from app.utils.network import resolve_instance_api_url
    instance = WahaInstance.query.get_or_404(id)
    instance.name = request.form.get('name')
    instance.api_url = resolve_instance_api_url(request.form.get('api_url'))
    instance.api_key = request.form.get('api_key')
    instance.session_name = request.form.get('session_name')
    db.session.commit()
    flash(f'✅ Instância WAHA "{instance.name}" atualizada com sucesso!')
    return redirect(url_for('admin.settings', tab='waha'))

@bp.route('/waha/<int:id>/sync_ip', methods=['POST'])
@login_required
@admin_required
def sync_waha_ip(id):
    import re
    from app.utils.network import get_connected_ip
    instance = WahaInstance.query.get_or_404(id)
    current_ip = get_connected_ip()
    if instance.api_url:
        instance.api_url = re.sub(r'https?://[^:/]+', f'http://{current_ip}', instance.api_url)
    else:
        instance.api_url = f'http://{current_ip}:3000'
    db.session.commit()
    flash(f'🔄 Instância "{instance.name}" atualizada para o IP conectado atual: {instance.api_url}')
    return redirect(url_for('admin.settings', tab='waha'))

@bp.route('/waha/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_waha_instance(id):
    instance = WahaInstance.query.get_or_404(id)
    name = instance.name
    was_default = instance.is_default
    db.session.delete(instance)
    
    if was_default:
        next_instance = WahaInstance.query.first()
        if next_instance:
            next_instance.is_default = True
            
    db.session.commit()
    flash(f'🗑️ Instância WAHA "{name}" removida.')
    return redirect(url_for('admin.settings', tab='waha'))

@bp.route('/waha/<int:id>/set_default', methods=['POST'])
@login_required
@admin_required
def set_default_waha_instance(id):
    # Remove default from all
    WahaInstance.query.update({WahaInstance.is_default: False})
    
    # Set default for selected
    instance = WahaInstance.query.get_or_404(id)
    instance.is_default = True
    db.session.commit()
    
    flash(f'⭐ Instância WAHA "{instance.name}" definida como padrão.')
    return redirect(url_for('admin.settings', tab='waha'))



# ── Módulo de Mensageria (Templates e Logs) ──────────────────────────────────
@bp.route('/templates', methods=['GET', 'POST'])
@login_required
@admin_required
def templates_list():
    if request.method == 'POST':
        name = request.form.get('name')
        text = request.form.get('text_content')
        if name and text:
            t = MessageTemplate(name=name, text_content=text)
            db.session.add(t)
            db.session.commit()
            flash(f'✅ Template "{name}" adicionado!')
        return redirect(url_for('admin.templates_list'))

    templates = MessageTemplate.query.all()
    return render_template('admin/templates.html', title='Templates de Mensagem', templates=templates)

@bp.route('/templates/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_template(id):
    t = MessageTemplate.query.get_or_404(id)
    db.session.delete(t)
    db.session.commit()
    flash(f'🗑️ Template removido.')
    return redirect(url_for('admin.templates_list'))

@bp.route('/messages')
@login_required
@admin_required
def message_logs():
    logs = MessageLog.query.order_by(MessageLog.timestamp.desc()).limit(200).all()
    return render_template('admin/message_logs.html', title='Monitoramento de Disparos', logs=logs)

# ── Logs ──────────────────────────────────────────────────────────────────────
@bp.route('/logs')
@login_required
@admin_required
def logs():
    all_logs = SystemLog.query.order_by(SystemLog.timestamp.desc()).limit(100).all()
    return render_template('admin/logs.html', title='Logs de Operação', logs=all_logs)


# ── Users list ────────────────────────────────────────────────────────────────
@bp.route('/users')
@login_required
@admin_required
def list_users():
    users = User.query.all()
    return render_template('admin/users.html', title='Gestão de Usuários', users=users)


# ── New user ───────────────────────────────────────────────────────────────────
@bp.route('/users/new', methods=['GET', 'POST'])
@login_required
@superadmin_required
def new_user():
    if request.method == 'POST':
        username = request.form.get('username')
        email    = request.form.get('email')
        role     = request.form.get('role', 'vendedor')
        password = request.form.get('password')
        xp       = int(request.form.get('performance_points', 0))

        if User.query.filter_by(username=username).first():
            flash('⚠️ Nome de usuário já existe.')
            return redirect(request.url)

        user = User(username=username, email=email, role=role, performance_points=xp)
        user.set_password(password)
        db.session.add(user)

        log = SystemLog(user_id=current_user.id,
                        action=f"Criou usuário: {username} ({role})")
        db.session.add(log)
        db.session.commit()
        flash(f'✅ Usuário {username} criado com sucesso!')
        return redirect(url_for('admin.list_users'))

    return render_template('admin/user_form.html', title='Novo Usuário')


# ── Edit user ─────────────────────────────────────────────────────────────────
@bp.route('/users/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@superadmin_required
def edit_user(id):
    user = User.query.get_or_404(id)
    if request.method == 'POST':
        user.email    = request.form.get('email')
        user.role     = request.form.get('role', 'vendedor')
        user.performance_points = int(request.form.get('performance_points', 0))

        password = request.form.get('password')
        if password:
            user.set_password(password)

        log = SystemLog(user_id=current_user.id,
                        action=f"Editou usuário: {user.username}")
        db.session.add(log)
        db.session.commit()
        flash(f'✅ Usuário {user.username} atualizado!')
        return redirect(url_for('admin.list_users'))

    return render_template('admin/user_form.html', title='Editar Usuário', user=user)


# ── Delete user ───────────────────────────────────────────────────────────────
@bp.route('/users/<int:id>/delete', methods=['POST'])
@login_required
@superadmin_required
def delete_user(id):
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash('⚠️ Você não pode excluir sua própria conta.')
        return redirect(url_for('admin.list_users'))
    name = user.username
    db.session.delete(user)
    log = SystemLog(user_id=current_user.id, action=f"Excluiu usuário: {name}")
    db.session.add(log)
    db.session.commit()
    flash(f'🗑️ Usuário {name} excluído.')
    return redirect(url_for('admin.list_users'))

# ── WAHA WhatsApp API (AJAX) ──────────────────────────────────────────────────
@bp.route('/api/waha/status', methods=['GET'])
@bp.route('/api/evolution/status', methods=['GET'])
@login_required
@admin_required
def waha_status():
    instance_id = request.args.get('instance_id')
    success, data = WahaAPI.get_connection_state(instance_id)
    return jsonify({'ok': success, 'data': data})

evo_status = waha_status

@bp.route('/api/waha/create', methods=['POST'])
@bp.route('/api/evolution/create', methods=['POST'])
@login_required
@admin_required
def waha_create():
    instance_id = request.args.get('instance_id')
    success, data = WahaAPI.create_instance(instance_id)
    return jsonify({'ok': success, 'data': data})

evo_create = waha_create

@bp.route('/api/waha/qr', methods=['GET'])
@bp.route('/api/evolution/qr', methods=['GET'])
@login_required
@admin_required
def waha_qr():
    instance_id = request.args.get('instance_id')
    success, data = WahaAPI.connect_instance(instance_id)
    return jsonify({'ok': success, 'data': data})

evo_qr = waha_qr

@bp.route('/api/waha/logout', methods=['POST'])
@bp.route('/api/evolution/logout', methods=['POST'])
@login_required
@admin_required
def waha_logout():
    instance_id = request.args.get('instance_id')
    success, data = WahaAPI.logout_instance(instance_id)
    return jsonify({'ok': success, 'data': data})

evo_logout = waha_logout

@bp.route('/api/waha/sessions', methods=['GET'])
@bp.route('/api/evolution/sessions', methods=['GET'])
@login_required
@admin_required
def waha_list_sessions():
    instance_id = request.args.get('instance_id')
    success, data = WahaAPI.list_sessions(instance_id)
    return jsonify({'ok': success, 'data': data})

evo_list_sessions = waha_list_sessions



# ── AI Tools ────────────────────────────────────────────────────────────────
@bp.route('/api/ai/improve', methods=['POST'])
@login_required
@admin_required
def ai_improve():
    data = request.json or {}
    text = data.get('text', '')
    if not text:
        return jsonify({'ok': False, 'error': 'Texto vazio'}), 400
    
    rewritten, error = AIHandler.rewrite_message(text)
    if error:
        return jsonify({'ok': False, 'error': error}), 400
    
    return jsonify({'ok': True, 'text': rewritten})

@bp.route('/api/ai/generate', methods=['POST'])
@login_required
@admin_required
def ai_generate():
    """Gera um novo texto/template a partir de uma instrução ou objetivo comercial."""
    data = request.json or {}
    instruction = data.get('prompt') or data.get('instruction') or ''
    if not instruction:
        return jsonify({'ok': False, 'error': 'Descreva o objetivo da mensagem a ser criada.'}), 400
    
    generated_text, error = AIHandler.generate_text(instruction)
    if error:
        return jsonify({'ok': False, 'error': error}), 400
        
    return jsonify({'ok': True, 'text': generated_text})

@bp.route('/api/ai/models', methods=['GET'])
@login_required
@admin_required
def ai_models():
    """Testa a conexão com o Ollama e lista os modelos instalados."""
    url = request.args.get('url')
    result = AIHandler.get_available_models(url)
    return jsonify(result)
