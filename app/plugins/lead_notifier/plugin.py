import logging
from app.core.plugins.base import BasePlugin

logger = logging.getLogger(__name__)

class LeadNotifierPlugin(BasePlugin):
    id = "lead_notifier"
    name = "Notificador de Novos Leads"
    sector = "gestao_clientes"
    version = "1.0.0"
    description = "Emite alertas em tempo real e insere notificações visuais quando novos leads dão entrada no CRM."
    author = "Equipe CRM Pro"
    icon = "fa-bell"

    def __init__(self, app=None):
        super().__init__(app)
        self.notifications_log = []

    def on_enable(self, app):
        super().on_enable(app)
        logger.info("[LeadNotifierPlugin] Plugin ativado e pronto para capturar novos leads!")

    def register_hooks(self, event_bus):
        event_bus.subscribe("client.created", self.on_client_created)

    def on_client_created(self, client_data):
        client_name = client_data.get('name', 'Novo Cliente') if isinstance(client_data, dict) else getattr(client_data, 'name', 'Novo Cliente')
        msg = f"🔔 Novo lead cadastrado: {client_name}"
        self.notifications_log.append(msg)
        logger.info(f"[LeadNotifierPlugin] Evento capturado: {msg}")

    def register_routes(self, app):
        from app.plugins.lead_notifier.routes import bp as lead_notifier_bp
        if 'lead_notifier' not in app.blueprints:
            app.register_blueprint(lead_notifier_bp, url_prefix='/plugins/lead-notifier')
