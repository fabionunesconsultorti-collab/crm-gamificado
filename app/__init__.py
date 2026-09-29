from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from config import Config

from sqlalchemy import MetaData

naming_convention = {
    "ix": 'ix_%(column_0_label)s',
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}
db = SQLAlchemy(metadata=MetaData(naming_convention=naming_convention))
migrate = Migrate()
login = LoginManager()
login.login_view = 'auth.login'
login.login_message = 'Por favor, faça login para acessar esta página.'

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    login.init_app(app)

    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from app.main import bp as main_bp
    app.register_blueprint(main_bp)

    from app.crm import bp as crm_bp
    app.register_blueprint(crm_bp, url_prefix='/crm')

    from app.admin import bp as admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')

    from app.api import bp as api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    from app.integrations import bp as integrations_bp
    app.register_blueprint(integrations_bp)

    # ── Descoberta e Inicialização dos Plugins Extensíveis ──
    try:
        from app.core.plugins.manager import PluginManager
        PluginManager.discover_and_load(app)
    except Exception as e:
        app.logger.error(f"[Plugins] Erro ao carregar motor de plugins: {e}")

    if not app.config.get('TESTING'):
        try:
            from app.tasks.backup_scheduler import start_backup_scheduler
            start_backup_scheduler(app)
        except Exception as e:
            app.logger.warning(f"Não foi possível iniciar o agendador de backup: {e}")

        try:
            import threading
            import time
            def _init_waha_webhook():
                time.sleep(2)
                with app.app_context():
                    try:
                        from app.utils.waha import WahaAPI
                        WahaAPI.ensure_webhook()
                    except Exception as ex:
                        app.logger.debug(f"[Waha Init] Não foi possível verificar webhook no startup: {ex}")
            threading.Thread(target=_init_waha_webhook, daemon=True, name="waha-webhook-init").start()
        except Exception as e:
            app.logger.warning(f"Erro ao agendar verificação do webhook WAHA: {e}")

    # ── Context processors: injeta helpers em todos os templates ──
    @app.context_processor
    def inject_ui_settings():
        """Injeta get_setting(), active_theme e custom_theme_vars em todos os templates."""
        from app.models import Setting
        import json
        def get_setting(key, default=''):
            try:
                return Setting.get_val(key, default)
            except Exception:
                return default
        try:
            active_theme = Setting.get_val('theme_name', 'dark-indigo') or 'dark-indigo'
        except Exception:
            active_theme = 'dark-indigo'

        custom_theme_json = get_setting('custom_theme_config', '{}')
        try:
            custom_theme_vars = json.loads(custom_theme_json) if custom_theme_json else {}
        except Exception:
            custom_theme_vars = {}

        def is_integration_active(provider):
            try:
                from app.integrations.manager import IntegrationManager
                adapter = IntegrationManager.get_adapter(provider)
                return bool(adapter and adapter.is_enabled())
            except Exception:
                return False

        def is_module_enabled(module_path):
            try:
                from app.core.module_registry import is_module_enabled as check_enabled
                return check_enabled(module_path)
            except Exception:
                return True

        def user_has_permission(resource, action):
            try:
                from app.core.permissions import user_has_permission as check_perm
                return check_perm(resource, action)
            except Exception:
                return True

        app_version = get_setting('system_version', 'v2.5.0') or 'v2.5.0'
        if not app_version.startswith('v') and app_version[0].isdigit():
            app_version = f"v{app_version}"

        return dict(
            get_setting=get_setting,
            active_theme=active_theme,
            custom_theme_vars=custom_theme_vars,
            custom_theme_json=custom_theme_json or '{}',
            is_integration_active=is_integration_active,
            is_module_enabled=is_module_enabled,
            user_has_permission=user_has_permission,
            app_version=app_version
        )

    return app

from app import models
