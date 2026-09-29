import logging

logger = logging.getLogger(__name__)

class BasePlugin:
    """
    Classe Abstrata de Contrato para Plugins do CRM.
    Todos os novos recursos e expansões devem herdar desta classe.
    """
    id: str = "base_plugin"
    name: str = "Base Plugin"
    sector: str = "gestao_clientes"  # gestao_clientes, ia_automacao, configuracao, integracoes, motor_plugins
    version: str = "1.0.0"
    description: str = "Plugin Base da Plataforma CRM"
    author: str = "Equipe CRM Pro"
    icon: str = "fa-puzzle-piece"

    def __init__(self, app=None):
        self.app = app
        self.is_enabled = False

    def on_load(self, app):
        """Executado quando o plugin é carregado na inicialização da aplicação."""
        self.app = app

    def on_enable(self, app):
        """Executado quando o plugin é ativado pelo administrador."""
        self.is_enabled = True
        logger.info(f"[PluginManager] Plugin '{self.name}' ({self.id}) foi ativado com sucesso.")

    def on_disable(self, app):
        """Executado quando o plugin é desativado."""
        self.is_enabled = False
        logger.info(f"[PluginManager] Plugin '{self.name}' ({self.id}) foi desativado.")

    def on_uninstall(self, app):
        """Executado na desinstalação permanente do plugin."""
        pass

    def register_routes(self, app):
        """Sobrescreva para registrar Blueprints ou rotas isoladas do plugin."""
        pass

    def register_hooks(self, event_bus):
        """Sobrescreva para inscrever callbacks no Barramento de Eventos (EventBus)."""
        pass

    def get_ui_widgets(self):
        """Retorna dicionário de widgets/HTML que o plugin injeta nas páginas do CRM."""
        return {}

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'sector': self.sector,
            'version': self.version,
            'description': self.description,
            'author': self.author,
            'icon': self.icon,
            'is_enabled': self.is_enabled
        }
