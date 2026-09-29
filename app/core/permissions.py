from functools import wraps
from flask import flash, redirect, url_for, request, jsonify
from flask_login import current_user

PERMISSION_RESOURCES = {
    'clients': {'name': 'Gestão de Clientes & Leads', 'actions': ['view', 'edit', 'delete']},
    'kanban': {'name': 'Funil Kanban de Vendas', 'actions': ['view', 'edit', 'delete']},
    'prospecting': {'name': 'Prospecção Ativa (Google Maps)', 'actions': ['view', 'edit', 'delete']},
    'waha_bulk': {'name': 'Disparo em Lote WhatsApp', 'actions': ['view', 'edit', 'delete']},
    'ai_knowledge': {'name': 'Base de Conhecimento RAG', 'actions': ['view', 'edit', 'delete']},
    'ai_bot': {'name': 'Fluxo IA do Bot / Auto-Responder', 'actions': ['view', 'edit', 'delete']},
    'integrations': {'name': 'Central de Integrações & Bling', 'actions': ['view', 'edit', 'delete']},
    'users': {'name': 'Usuários & Permissões', 'actions': ['view', 'edit', 'delete']},
    'system_settings': {'name': 'Configurações Globais & Temas', 'actions': ['view', 'edit', 'delete']},
    'plugins': {'name': 'Plugins & Extensões', 'actions': ['view', 'edit', 'delete']},
    'logs': {'name': 'Logs do Sistema & Auditoria', 'actions': ['view', 'edit', 'delete']}
}

ACTION_LABELS = {
    'view': 'Visualizar',
    'edit': 'Editar / Criar',
    'delete': 'Excluir'
}

def user_has_permission(resource: str, action: str) -> bool:
    if not current_user or not current_user.is_authenticated:
        return False
    return current_user.has_permission(resource, action)

def requires_permission(resource: str, action: str):
    """Decorator para rotas HTTP que exigem permissão (resource, action)."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            if not current_user.has_permission(resource, action):
                action_label = ACTION_LABELS.get(action, action)
                resource_data = PERMISSION_RESOURCES.get(resource, {'name': resource})
                msg = f"Você não possui permissão para {action_label.lower()} em '{resource_data['name']}'."
                if request.is_json or request.path.startswith('/api/'):
                    return jsonify({'success': False, 'error': msg, 'permission_denied': True}), 403
                flash(f"⚠️ {msg}", 'warning')
                return redirect(url_for('main.index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator
