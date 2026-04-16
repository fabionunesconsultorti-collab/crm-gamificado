from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.admin import bp
from app.models import Setting, User, SystemLog, Client, Store, MessageTemplate, MessageLog
from app.utils.waha import WahaAPI
import os
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


# ── Settings ──────────────────────────────────────────────────────────────────
@bp.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    if request.method == 'POST':
        keys = ['msg_boas_vindas', 'msg_proposta', 'msg_fechamento', 'frase_bom_dia', 'evo_api_url', 'evo_api_key', 'evo_instance']
        for key in keys:
            val = request.form.get(key)
            setting = Setting.query.filter_by(key=key).first()
            if not setting:
                setting = Setting(key=key, value=val)
                db.session.add(setting)
            else:
                setting.value = val
        db.session.commit()
        flash('✅ Configurações atualizadas com sucesso!')
        return redirect(url_for('admin.settings'))

    all_settings = {s.key: s.value for s in Setting.query.all()}
    stores = Store.query.all()
    return render_template('admin/settings.html', title='Configurações do Sistema',
                           settings=all_settings, stores=stores)

@bp.route('/stores/new', methods=['POST'])
@login_required
@admin_required
def new_store():
    name = request.form.get('name')
    if name:
        store = Store(name=name)
        db.session.add(store)
        db.session.commit()
        flash(f'✅ Loja "{name}" adicionada com sucesso!')
    return redirect(url_for('admin.settings'))

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
    return redirect(url_for('admin.settings'))


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

# ── Evolution API (AJAX) ──────────────────────────────────────────────────────
@bp.route('/api/evolution/status', methods=['GET'])
@login_required
@admin_required
def evo_status():
    success, data = WahaAPI.get_connection_state()
    return jsonify({'ok': success, 'data': data})

@bp.route('/api/evolution/create', methods=['POST'])
@login_required
@admin_required
def evo_create():
    success, data = WahaAPI.create_instance()
    return jsonify({'ok': success, 'data': data})

@bp.route('/api/evolution/qr', methods=['GET'])
@login_required
@admin_required
def evo_qr():
    success, data = WahaAPI.connect_instance()
    return jsonify({'ok': success, 'data': data})

@bp.route('/api/evolution/logout', methods=['POST'])
@login_required
@admin_required
def evo_logout():
    success, data = WahaAPI.logout_instance()
    return jsonify({'ok': success, 'data': data})

@bp.route('/api/evolution/sessions', methods=['GET'])
@login_required
@admin_required
def evo_list_sessions():
    success, data = WahaAPI.list_sessions()
    return jsonify({'ok': success, 'data': data})


