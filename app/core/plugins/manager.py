import os
import json
import importlib
import logging
from typing import Dict, Type, List, Optional
from app.core.plugins.base import BasePlugin
from app.core.plugins.event_bus import EventBus

logger = logging.getLogger(__name__)

class PluginManager:
    """
    Gerenciador Central de Plugins do CRM.
    Descreve, carrega, ativa e desativa plugins dinâmicos em 'app/plugins/'.
    """
    _plugins: Dict[str, BasePlugin] = {}
    _loaded = False
    _app = None

    @classmethod
    def get_plugin_dir(cls) -> str:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(base_dir, 'plugins')

    @classmethod
    def discover_and_load(cls, app=None):
        """Descobre todos os plugins na pasta app/plugins/ e inicializa seus ciclos de vida."""
        if app:
            cls._app = app

        plugins_dir = cls.get_plugin_dir()
        if not os.path.exists(plugins_dir):
            os.makedirs(plugins_dir, exist_ok=True)
            return

        for item in os.listdir(plugins_dir):
            item_path = os.path.join(plugins_dir, item)
            if os.path.isdir(item_path) and not item.startswith('_') and not item.startswith('.'):
                cls._load_single_plugin(item, item_path)

        cls._loaded = True

    @classmethod
    def _load_single_plugin(cls, plugin_id: str, plugin_path: str):
        plugin_file = os.path.join(plugin_path, 'plugin.py')
        if not os.path.exists(plugin_file):
            return

        try:
            module_name = f"app.plugins.{plugin_id}.plugin"
            mod = importlib.import_module(module_name)
            
            # Procura classe herdada de BasePlugin
            plugin_class = None
            for attr in dir(mod):
                obj = getattr(mod, attr)
                if isinstance(obj, type) and issubclass(obj, BasePlugin) and obj is not BasePlugin:
                    plugin_class = obj
                    break

            if not plugin_class:
                logger.warning(f"[PluginManager] Nenhuma classe herdada de BasePlugin encontrada em {plugin_id}")
                return

            instance: BasePlugin = plugin_class(app=cls._app)
            instance.id = plugin_id

            # Carrega manifesto JSON se existir
            manifest_path = os.path.join(plugin_path, 'plugin.json')
            if os.path.exists(manifest_path):
                try:
                    with open(manifest_path, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                        instance.name = meta.get('name', instance.name)
                        instance.version = meta.get('version', instance.version)
                        instance.sector = meta.get('sector', instance.sector)
                        instance.description = meta.get('description', instance.description)
                        instance.author = meta.get('author', instance.author)
                        instance.icon = meta.get('icon', instance.icon)
                except Exception as e:
                    logger.debug(f"[PluginManager] Erro ao ler manifesto do plugin {plugin_id}: {e}")

            cls._plugins[plugin_id] = instance
            instance.on_load(cls._app)

            # Verifica se está habilitado no banco
            is_enabled = cls.is_plugin_enabled(plugin_id)
            if is_enabled:
                instance.on_enable(cls._app)
                instance.register_hooks(EventBus)
                if cls._app:
                    instance.register_routes(cls._app)

            logger.info(f"[PluginManager] Plugin registrado: '{instance.name}' ({plugin_id}) - Ativo: {is_enabled}")

        except Exception as e:
            logger.error(f"[PluginManager] Falha ao carregar plugin '{plugin_id}': {e}", exc_info=True)

    @classmethod
    def is_plugin_enabled(cls, plugin_id: str) -> bool:
        """Verifica no banco de dados se o plugin está ativado."""
        try:
            from app.models import Setting
            key = f"plugin_{plugin_id}_enabled"
            val = Setting.get_val(key, 'true')  # Por padrão, novos plugins detectados ficam ativos
            return str(val).strip().lower() in ['true', '1', 'yes', 'sim']
        except Exception:
            return True

    @classmethod
    def toggle_plugin(cls, plugin_id: str, enable: bool) -> dict:
        """Ativa ou desativa um plugin em runtime."""
        plugin = cls._plugins.get(plugin_id)
        if not plugin:
            return {'success': False, 'message': f'Plugin "{plugin_id}" não encontrado.'}

        try:
            from app import db
            from app.models import Setting
            key = f"plugin_{plugin_id}_enabled"
            val_str = 'true' if enable else 'false'
            Setting.set_val(key, val_str)
            db.session.commit()

            if enable:
                plugin.on_enable(cls._app)
                plugin.register_hooks(EventBus)
                if cls._app:
                    plugin.register_routes(cls._app)
            else:
                plugin.on_disable(cls._app)

            return {
                'success': True,
                'message': f"Plugin '{plugin.name}' {'ativado' if enable else 'desativado'} com sucesso.",
                'is_enabled': enable
            }
        except Exception as e:
            logger.error(f"[PluginManager] Erro ao alterar estado do plugin {plugin_id}: {e}")
            return {'success': False, 'message': str(e)}

    @classmethod
    def get_all_plugins(cls) -> List[dict]:
        """Retorna lista de dicionários com todos os plugins descobertos."""
        if not cls._loaded:
            cls.discover_and_load()
        return [p.to_dict() for p in cls._plugins.values()]

    @classmethod
    def get_plugin(cls, plugin_id: str) -> Optional[BasePlugin]:
        return cls._plugins.get(plugin_id)
