import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'você-nunca-vai-adivinhar'
    # Suporte a DATABASE_URL ou PostgreSQL
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        if os.environ.get('USE_SQLITE', '').lower() in ('true', '1'):
            db_url = 'sqlite:///' + os.path.join(os.path.abspath(os.path.dirname(__file__)), 'crm.db')
        else:
            pg_user = os.environ.get('POSTGRES_USER', 'waha_user')
            pg_pass = os.environ.get('POSTGRES_PASSWORD', 'waha_password')
            pg_host = os.environ.get('POSTGRES_HOST', 'localhost')
            pg_port = os.environ.get('POSTGRES_PORT', '5432')
            pg_db = os.environ.get('POSTGRES_DB', 'crm_db')
            db_url = f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"

    if db_url and db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)

    SQLALCHEMY_DATABASE_URI = db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith('postgresql'):
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,
            "pool_recycle": int(os.environ.get("DB_POOL_RECYCLE", 1800)),
            "pool_size": int(os.environ.get("DB_POOL_SIZE", 10)),
            "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", 20)),
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {}
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'
    MAPS_SCRAPER_URL = os.environ.get('MAPS_SCRAPER_URL') or 'http://localhost:8080'

