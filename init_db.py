import os
from app import create_app, db
from app.models import User, Setting, WahaInstance
from app.core.module_registry import SECTORS, ModuleRegistry
from app.utils.network import get_connected_ip, resolve_instance_api_url

# Configurações padrão do ecossistema CRM Pro
DEFAULT_SYSTEM_SETTINGS = {
    'ai_provider': 'ollama',
    'ai_ollama_url': 'http://localhost:11434',
    'ai_ollama_model': 'llama3.2',
    'whatsapp_bot_enabled': 'true',
    'whatsapp_bot_ignore_groups': 'true',
    'whatsapp_bot_ignore_broadcast': 'true',
    'whatsapp_send_seen': 'true',
    'whatsapp_simulate_typing': 'true',
    'whatsapp_debounce_delay': '12',
    'whatsapp_history_turns': '8',
    'whatsapp_history_ttl_hours': '4',
    'whatsapp_bot_persona_name': 'Sofia',
    'whatsapp_bot_company_name': 'CRM Pro',
    'whatsapp_bot_system_prompt': (
        'Você é atendente oficial de WhatsApp da empresa CRM Pro. '
        'Sua função é fornecer respostas padronizadas, curtas e estritamente objetivas (máximo de 1 a 2 frases diretas no estilo WhatsApp comercial). '
        'Responda dúvidas comerciais e operacionais com base exclusivamente nas informações oficiais da empresa. '
        'NUNCA aja como IA genérica, robô ou ChatGPT. NUNCA cite termos técnicos internos como TensorFlow, Diretiva, RAG ou Prompt. '
        'REGRA CRÍTICA DE FALTA DE CONTEXTO: Se você não entender com precisão o contexto da mensagem, se for ambígua ou sem sentido: '
        'pause o atendimento emitindo [PAUSAR_ATENDIMENTO] Não consegui compreender o contexto da sua mensagem. Vou pausar o atendimento automático para que nossa equipe humana dê continuidade por aqui em instantes.'
    ),
    'whatsapp_bot_fallback_msg': 'Olá! Recebemos sua mensagem e nossa equipe retornará em instantes.',
    'whatsapp_bot_context_pause_msg': 'Não consegui compreender o contexto da sua mensagem. Pausei o atendimento automático para que nossa equipe humana dê continuidade por aqui em instantes.',
    'whatsapp_bot_handover_trigger': 'humano, atendente, falar com pessoa, falar com alguem, atendente humano, suporte humano, cancelar',
    'whatsapp_bot_handover_msg': 'Com certeza! Estou direcionando seu atendimento para um de nossos consultores humanos. Em instantes alguém da equipe responderá aqui.',
    'whatsapp_bot_work_hours_enabled': 'false',
    'whatsapp_bot_work_hours_start': '08:00',
    'whatsapp_bot_work_hours_end': '18:00',
    'whatsapp_bot_out_of_hours_msg': 'Olá! No momento estamos fora do nosso horário de atendimento (Seg à Sex, 08h às 18h). Deixe sua mensagem que responderemos assim que retornarmos!',
    'whatsapp_bot_auto_create_lead': 'true',
    'whatsapp_bot_inject_client_data': 'true'
}

# Feature Flags dos Módulos dos 5 Setores
for sector_key, sector_data in SECTORS.items():
    for mod_key in sector_data['modules'].keys():
        flag_key = ModuleRegistry.get_setting_key(sector_key, mod_key)
        if flag_key not in DEFAULT_SYSTEM_SETTINGS:
            DEFAULT_SYSTEM_SETTINGS[flag_key] = 'true'


def init_database(app=None):
    """Executa a inicialização segura do banco de dados, migrações de colunas e defaults."""
    if not app:
        app = create_app()

    with app.app_context():
        db.create_all()

        # Garante colunas de prospecção na tabela client se a tabela já existir no PostgreSQL ou SQLite
        try:
            from sqlalchemy import text
            is_postgres = db.engine.dialect.name == 'postgresql'
            
            if is_postgres:
                db.session.execute(text("ALTER TABLE client ADD COLUMN IF NOT EXISTS website TEXT;"))
                db.session.execute(text("ALTER TABLE client ADD COLUMN IF NOT EXISTS category VARCHAR(256);"))
                db.session.execute(text("ALTER TABLE client ADD COLUMN IF NOT EXISTS segment VARCHAR(256);"))
                db.session.execute(text("ALTER TABLE client ADD COLUMN IF NOT EXISTS instagram VARCHAR(256);"))
                db.session.execute(text("ALTER TABLE client ADD COLUMN IF NOT EXISTS google_rating FLOAT DEFAULT 0.0;"))
                db.session.execute(text("ALTER TABLE client ADD COLUMN IF NOT EXISTS google_reviews_count INTEGER DEFAULT 0;"))
                db.session.execute(text("ALTER TABLE client ADD COLUMN IF NOT EXISTS bot_enabled BOOLEAN DEFAULT TRUE;"))
                db.session.execute(text("ALTER TABLE client ALTER COLUMN cpf TYPE VARCHAR(32);"))
                db.session.execute(text("ALTER TABLE scraping_job ADD COLUMN IF NOT EXISTS query_term VARCHAR(256);"))
                db.session.execute(text("ALTER TABLE scraping_job ADD COLUMN IF NOT EXISTS progress INTEGER DEFAULT 0;"))
                db.session.execute(text("ALTER TABLE scraping_job ADD COLUMN IF NOT EXISTS current_step VARCHAR(128) DEFAULT '';"))
                db.session.execute(text("ALTER TABLE waha_instance ADD COLUMN IF NOT EXISTS behavior_guide_id INTEGER REFERENCES behavior_guide(id);"))
                
                # Sincroniza dados legados: copia category para segment se segment for nulo
                db.session.execute(text("UPDATE client SET segment = category WHERE segment IS NULL AND category IS NOT NULL;"))
                # Se website tiver link de instagram, copia para o campo instagram
                db.session.execute(text("UPDATE client SET instagram = website WHERE website ILIKE '%instagram.com%' AND (instagram IS NULL OR instagram = '');"))
            else:
                # SQLite fallback
                for col, col_type in [
                    ("website", "TEXT"),
                    ("category", "VARCHAR(256)"),
                    ("segment", "VARCHAR(256)"),
                    ("instagram", "VARCHAR(256)"),
                    ("google_rating", "FLOAT DEFAULT 0.0"),
                    ("google_reviews_count", "INTEGER DEFAULT 0"),
                    ("bot_enabled", "BOOLEAN DEFAULT 1")
                ]:
                    try:
                        db.session.execute(text(f"ALTER TABLE client ADD COLUMN {col} {col_type};"))
                        db.session.commit()
                    except Exception:
                        db.session.rollback()

                try:
                    db.session.execute(text("ALTER TABLE waha_instance ADD COLUMN behavior_guide_id INTEGER REFERENCES behavior_guide(id);"))
                    db.session.commit()
                except Exception:
                    db.session.rollback()

                try:
                    db.session.execute(text("UPDATE client SET segment = category WHERE segment IS NULL AND category IS NOT NULL;"))
                    db.session.commit()
                except Exception:
                    db.session.rollback()

            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Nota na migração de colunas do client: {e}")

        # Verifica se o administrador existe
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            new_admin = User(username='admin', email='admin@crmpro.com', role='admin')
            new_admin.set_password('admin123')
            db.session.add(new_admin)
            db.session.commit()
            print("Usuário Admin criado com sucesso!")
            print("Usuário: admin")
            print("Senha: admin123")
        else:
            print("Usuário Admin já existe.")

        # Inicializa configurações padrão
        for key, val in DEFAULT_SYSTEM_SETTINGS.items():
            if not Setting.query.filter_by(key=key).first():
                db.session.add(Setting(key=key, value=val))

        # Inicializa ou corrige instância padrão WAHA
        connected_ip = get_connected_ip()
        default_waha_url = os.environ.get('WAHA_API_URL') or f'http://{connected_ip}:3000'
        default_waha_key = os.environ.get('WAHA_API_KEY') or 'admin123'

        waha_inst = WahaInstance.query.first()
        if not waha_inst:
            waha_inst = WahaInstance(
                name='Servidor Padrão',
                api_url=default_waha_url,
                api_key=default_waha_key,
                session_name='default',
                is_default=True
            )
            db.session.add(waha_inst)
        else:
            if '192.168.1.44' in (waha_inst.api_url or '') or not waha_inst.api_url:
                waha_inst.api_url = default_waha_url
            else:
                waha_inst.api_url = resolve_instance_api_url(waha_inst.api_url)

        # Inicializa o Guia de Comportamento padrão inicial a partir do arquivo guia_de_comportamento_bot_de_vendas_ti_para_pmes.md
        try:
            from app.utils.behavior_parser import BehaviorParser
            BehaviorParser.seed_initial_guide_if_empty()
        except Exception as guide_err:
            print(f"Nota na inicialização do guia de comportamento: {guide_err}")

        db.session.commit()
        print("Banco de dados sincronizado e inicializado com sucesso.")


if __name__ == '__main__':
    init_database()
