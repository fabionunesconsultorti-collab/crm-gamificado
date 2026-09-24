import os
from app import create_app, db
from app.models import User, Setting

app = create_app()

with app.app_context():
    db.create_all()

    # Garante colunas de prospecção na tabela client se a tabela já existir no PostgreSQL ou SQLite
    try:
        from sqlalchemy import text
        # Verifica se o banco é Postgres ou SQLite
        is_postgres = db.engine.dialect.name == 'postgresql'
        
        if is_postgres:
            db.session.execute(text("ALTER TABLE client ADD COLUMN IF NOT EXISTS website TEXT;"))
            db.session.execute(text("ALTER TABLE client ADD COLUMN IF NOT EXISTS category VARCHAR(256);"))
            db.session.execute(text("ALTER TABLE client ADD COLUMN IF NOT EXISTS segment VARCHAR(256);"))
            db.session.execute(text("ALTER TABLE client ADD COLUMN IF NOT EXISTS instagram VARCHAR(256);"))
            db.session.execute(text("ALTER TABLE client ADD COLUMN IF NOT EXISTS google_rating FLOAT DEFAULT 0.0;"))
            db.session.execute(text("ALTER TABLE client ADD COLUMN IF NOT EXISTS google_reviews_count INTEGER DEFAULT 0;"))
            db.session.execute(text("ALTER TABLE client ALTER COLUMN cpf TYPE VARCHAR(32);"))
            db.session.execute(text("ALTER TABLE scraping_job ADD COLUMN IF NOT EXISTS query_term VARCHAR(256);"))
            db.session.execute(text("ALTER TABLE scraping_job ADD COLUMN IF NOT EXISTS progress INTEGER DEFAULT 0;"))
            db.session.execute(text("ALTER TABLE scraping_job ADD COLUMN IF NOT EXISTS current_step VARCHAR(128) DEFAULT '';"))
            
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
                ("google_reviews_count", "INTEGER DEFAULT 0")
            ]:
                try:
                    db.session.execute(text(f"ALTER TABLE client ADD COLUMN {col} {col_type};"))
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

    
    # Check if admin already exists
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

    # Inicializa configurações padrão para Ollama e Bot de Respostas WhatsApp se ainda não existirem
    default_settings = {
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
            'Você é um assistente comercial educado, atencioso e prestativo. Responda de forma clara, natural, '
            'profissional e amigável em português do Brasil. Mantenha respostas curtas e fáceis de ler no celular '
            '(1 a 3 parágrafos curtos). Seu objetivo é tirar dúvidas sobre nossos serviços, qualificar o interesse do '
            'lead e propor que um consultor da equipe entre em contato para prosseguir com a proposta.'
        ),
        'whatsapp_bot_fallback_msg': 'Olá! Recebemos sua mensagem e nossa equipe retornará em instantes.',
        'whatsapp_bot_handover_trigger': 'humano, atendente, falar com pessoa, falar com alguem, atendente humano, suporte humano, cancelar',
        'whatsapp_bot_handover_msg': 'Com certeza! Estou direcionando seu atendimento para um de nossos consultores humanos. Em instantes alguém da equipe responderá aqui.',
        'whatsapp_bot_work_hours_enabled': 'false',
        'whatsapp_bot_work_hours_start': '08:00',
        'whatsapp_bot_work_hours_end': '18:00',
        'whatsapp_bot_out_of_hours_msg': 'Olá! No momento estamos fora do nosso horário de atendimento (Seg à Sex, 08h às 18h). Deixe sua mensagem que responderemos assim que retornarmos!',
        'whatsapp_bot_auto_create_lead': 'true',
        'whatsapp_bot_inject_client_data': 'true'
    }
    for key, val in default_settings.items():
        if not Setting.query.filter_by(key=key).first():
            db.session.add(Setting(key=key, value=val))


    
    # Inicializa ou corrige instância padrão WAHA buscando dinamicamente o IP conectado ou variável de ambiente
    from app.models import WahaInstance
    from app.utils.network import get_connected_ip, resolve_instance_api_url
    
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
        # Se contiver 192.168.1.44 ou URL vazia, resolve para a URL padrão configurada
        if '192.168.1.44' in (waha_inst.api_url or '') or not waha_inst.api_url:
            waha_inst.api_url = default_waha_url
            waha_inst.api_key = waha_inst.api_key or default_waha_key
        else:
            waha_inst.api_url = resolve_instance_api_url(waha_inst.api_url)
    db.session.commit()

