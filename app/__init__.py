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

    return app

from app import models
