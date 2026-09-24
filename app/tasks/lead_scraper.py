import re
import time
import logging
import threading
from datetime import datetime, timezone
from app import db
from app.models import Client, ScrapingJob, User
from app.utils.maps_scraper import MapsScraperClient

logger = logging.getLogger(__name__)

# Lista de DDDs válidos no Brasil
BRAZIL_DDDS = {
    '11', '12', '13', '14', '15', '16', '17', '18', '19', # SP
    '21', '22', '24', # RJ
    '27', '28', # ES
    '31', '32', '33', '34', '35', '37', '38', # MG
    '41', '42', '43', '44', '45', '46', # PR
    '47', '48', '49', # SC
    '51', '53', '54', '55', # RS
    '61', # DF
    '62', '64', # GO
    '63', # TO
    '65', '66', # MT
    '67', # MS
    '68', # AC
    '69', # RO
    '71', '73', '74', '75', '77', # BA
    '79', # SE
    '81', '87', # PE
    '82', # AL
    '83', # PB
    '84', # RN
    '85', '88', # CE
    '86', '89', # PI
    '91', '93', '94', # PA
    '92', '97', # AM
    '95', # RR
    '96', # AP
    '98', '99'  # MA
}

def normalize_brazilian_phone(raw_phone: str) -> tuple[str | None, bool, bool]:
    """
    Normaliza e valida um telefone brasileiro para o padrão E.164 (55 + DDD + Número).
    Retorna uma tupla: (telefone_normalizado, is_valido, is_celular).
    Exemplos:
      - "(19) 99876-5432" -> ("5519998765432", True, True)
      - "+55 19 3876-5432" -> ("551938765432", True, False)
      - "019998765432" -> ("5519998765432", True, True)
      - "19 9876-5432" (móvel antigo sem nono dígito) -> ("5519998765432", True, True)
    """
    if not raw_phone:
        return None, False, False

    # Remove todos os caracteres não numéricos
    digits = re.sub(r'\D', '', str(raw_phone))
    if not digits:
        return None, False, False

    # Remove prefixo internacional 00 ou 0055 se presente
    if digits.startswith('0055'):
        digits = digits[4:]
    elif digits.startswith('00'):
        digits = digits[2:]

    # Remove zero à esquerda do DDD (ex: 019998765432 -> 19998765432)
    if digits.startswith('0') and len(digits) in (11, 12):
        digits = digits[1:]

    # Se já começar com DDI 55
    if digits.startswith('55') and len(digits) in (12, 13):
        national = digits[2:]
    else:
        national = digits

    # Validação do DDD (2 primeiros dígitos)
    if len(national) < 10:
        return None, False, False

    ddd = national[:2]
    if ddd not in BRAZIL_DDDS:
        # Se os dígitos totais forem 12 ou 13 mas não começou com 55 testado acima
        if len(digits) in (12, 13) and digits[:2] == '55' and digits[2:4] in BRAZIL_DDDS:
            ddd = digits[2:4]
            national = digits[2:]
        else:
            return None, False, False

    local_number = national[2:]

    # Análise de Celular vs Fixo
    # Telefone com 9 dígitos locais (celular padrão): 9 + 8 dígitos
    if len(local_number) == 9:
        if local_number.startswith('9'):
            return f"55{ddd}{local_number}", True, True
        else:
            return f"55{ddd}{local_number}", True, False

    # Telefone com 8 dígitos locais
    elif len(local_number) == 8:
        first_digit = local_number[0]
        # Celulares iniciam com 6, 7, 8 ou 9 no Brasil (antes da regra do 9º dígito obrigatório)
        if first_digit in ('6', '7', '8', '9'):
            # Converte para padrão moderno de 9 dígitos
            modern_number = f"9{local_number}"
            return f"55{ddd}{modern_number}", True, True
        # Fixo inicia com 2, 3, 4 ou 5
        elif first_digit in ('2', '3', '4', '5'):
            return f"55{ddd}{local_number}", True, False
        else:
            return f"55{ddd}{local_number}", True, False

    return None, False, False

def run_lead_scraper_task(job_id: int):
    """
    Ciclo de vida completo da tarefa em segundo plano de prospecção ativa de leads:
    1. Busca registro do ScrapingJob no banco e marca como 'processing'.
    2. Submete o job para o container gosom/google-maps-scraper via REST API.
    3. Realiza polling seguro até finalização.
    4. Baixa e higieniza cada registro de empresa retornado.
    5. Deduplica e insere novos leads na tabela Client na etapa inicial do funil ('lead').
    6. Atualiza ScrapingJob com totais minerados/importados e status final.
    """
    logger.info(f"[LeadScraper Task] Iniciando execução do Job ID {job_id}")
    job = ScrapingJob.query.get(job_id)
    if not job:
        logger.error(f"[LeadScraper Task] Job ID {job_id} não encontrado no banco de dados.")
        return

    client_api = MapsScraperClient()
    if not client_api.is_online():
        error_msg = "Servidor do Google Maps Scraper indisponível na porta 8080. Verifique os containers Docker."
        logger.error(f"[LeadScraper Task] {error_msg}")
        job.status = 'failed'
        job.error_message = error_msg
        job.finished_at = datetime.utcnow()
        db.session.commit()
        return

    job.status = 'processing'
    job.progress = 10
    job.current_step = 'Conectando ao Google Maps Scraper...'
    db.session.commit()

    try:
        # 1. Dispara o job no Scraper
        external_id = client_api.create_job(
            queries=[job.query_term],
            depth=job.depth,
            extract_emails=job.extract_emails,
            name=f"CRM Job {job.id} - {job.query_term}"
        )
        job.external_job_id = external_id
        job.progress = 20
        job.current_step = f'Buscando "{job.query_term}" no Google Maps...'
        db.session.commit()
        logger.info(f"[LeadScraper Task] Job disparado no scraper externo com ID={external_id}")

        # 2. Polling até finalização (limite máximo de 20 minutos)
        max_wait_seconds = 1200
        start_time = time.time()
        poll_interval = 2.5
        is_completed = False

        while (time.time() - start_time) < max_wait_seconds:
            elapsed = time.time() - start_time
            status_data = client_api.check_status(external_id)
            current_status = status_data.get("status")
            logger.info(f"[LeadScraper Task] Polling Job {external_id}: status={current_status} (elapsed={int(elapsed)}s)")

            if current_status == "completed":
                is_completed = True
                break
            elif current_status == "failed":
                raise RuntimeError(f"O scraper externo falhou na execução do job {external_id}.")

            # Atualiza o progresso visual de forma progressiva durante a navegação
            if elapsed < 8:
                new_progress = 25
                new_step = 'Navegando no Google Maps e localizando listagem...'
            elif elapsed < 16:
                new_progress = 45
                new_step = 'Extraindo nomes, endereços e categorias das empresas...'
            elif elapsed < 26:
                new_progress = 65
                new_step = 'Coletando telefones, websites, avaliações e notas...'
            elif elapsed < 40:
                new_progress = 75
                new_step = 'Escaneando sites para extração profunda de e-mails...' if job.extract_emails else 'Compilando listagem de estabelecimentos...'
            else:
                new_progress = min(82, 75 + int((elapsed - 40) / 10))
                new_step = 'Finalizando extração no Google Maps...'

            if new_progress != job.progress or new_step != job.current_step:
                job.progress = new_progress
                job.current_step = new_step
                db.session.commit()

            time.sleep(poll_interval)

        if not is_completed:
            raise TimeoutError(f"Tempo limite excedido ({max_wait_seconds}s) aguardando o scraper concluir o job.")

        # 3. Download e higienização dos resultados
        job.progress = 85
        job.current_step = 'Baixando resultados e iniciando higienização de contatos...'
        db.session.commit()

        raw_items = client_api.fetch_results(external_id)
        job.total_scraped = len(raw_items)
        logger.info(f"[LeadScraper Task] {len(raw_items)} registros brutos baixados do scraper.")

        job.progress = 90
        job.current_step = f'Normalizando telefones E.164 e deduplicando {len(raw_items)} empresas...'
        db.session.commit()

        imported_count = 0
        assigned_user_id = job.created_by_user_id
        if not assigned_user_id:
            first_admin = User.query.filter_by(role='admin').first()
            assigned_user_id = first_admin.id if first_admin else None

        from app.utils.encoding import sanitize_encoding

        for item in raw_items:
            name = sanitize_encoding(item.get("name"))
            if not name:
                continue

            raw_phone = item.get("phone")
            norm_phone, is_valid_phone, is_mobile = normalize_brazilian_phone(raw_phone)

            # Deduplicação: se o telefone for válido, verifica se já existe na base Client
            if norm_phone:
                existing = Client.query.filter_by(phone=norm_phone).first()
                if not existing and len(norm_phone) >= 10:
                    # Verifica também por sufixo dos últimos 8 dígitos
                    suffix = norm_phone[-8:]
                    existing = Client.query.filter(Client.phone.endswith(suffix)).first()
                
                if existing:
                    # Lead já existente: apenas anexa a tag da busca nas badges se ainda não tiver
                    existing_badges = existing.badges or ''
                    if f"job_{job.id}" not in existing_badges:
                        existing.badges = f"{existing_badges},job_{job.id}".strip(',')
                    continue
            else:
                # Se não tem telefone, verifica deduplicação por nome idêntico para evitar poluição
                existing_by_name = Client.query.filter_by(name=name).first()
                if existing_by_name:
                    continue

            # Cria novo Lead no CRM
            badges_list = ["outbound_gmaps", f"job_{job.id}"]
            if is_mobile:
                badges_list.append("whatsapp_valido")
            if item.get("email"):
                badges_list.append("tem_email")

            category_val = sanitize_encoding((item.get("category") or "").strip()[:256]) or None
            address_val = sanitize_encoding(item.get("address")) or None
            website_val = (item.get("website") or "").strip() or None
            instagram_val = (item.get("instagram") or "").strip() or None
            clean_query = sanitize_encoding(job.query_term)

            # Se o website for do Instagram e instagram_val estiver vazio
            if website_val and "instagram.com" in website_val.lower() and not instagram_val:
                instagram_val = website_val

            notes_content = (
                f"🎯 Prospecção Ativa (Google Maps)\n"
                f"Termo pesquisado: '{clean_query}'\n"
                f"Segmento: {category_val or 'Não informado'}\n"
                f"Avaliação: {item.get('rating', 0.0)}⭐ ({item.get('reviews_count', 0)} avaliações)\n"
                f"Instagram: {instagram_val or 'Não informado'}\n"
                f"Website: {website_val or 'Não informado'}\n"
                f"Endereço: {address_val or 'Não informado'}"
            )

            new_client = Client(
                name=name[:128],
                phone=norm_phone or None,
                email=(item.get("email") or "").strip()[:128] or None,
                website=website_val,
                instagram=instagram_val,
                address=address_val,
                category=category_val,
                segment=category_val, # Segmento populado pela Prospecção Ativa
                google_rating=float(item.get("rating") or 0.0),
                google_reviews_count=int(item.get("reviews_count") or 0),
                status='lead', # Primeira coluna do funil Kanban
                lead_source='Google Maps',
                notes=notes_content,
                badges=",".join(badges_list),
                opt_in=False, # Conformidade LGPD para outbound
                data_usage_purpose='Prospecção comercial B2B via dados públicos do Google Maps',
                assigned_to=assigned_user_id
            )

            db.session.add(new_client)
            imported_count += 1

        db.session.commit()

        job.total_imported = imported_count
        job.progress = 100
        job.current_step = f'Concluído! {imported_count} novos leads adicionados ao funil.'
        job.status = 'completed'
        job.finished_at = datetime.utcnow()
        db.session.commit()
        logger.info(f"[LeadScraper Task] Job ID {job.id} concluído com sucesso: {imported_count} novos leads importados.")

    except Exception as e:
        db.session.rollback()
        logger.error(f"[LeadScraper Task] Erro fatal durante execução do Job {job.id}: {e}", exc_info=True)
        job.status = 'failed'
        job.progress = 100
        job.current_step = f'Falhou: {str(e)[:80]}'
        job.error_message = str(e)
        job.finished_at = datetime.utcnow()
        db.session.commit()

def dispatch_scraping_job(job_id: int):
    """
    Despacha o processamento do job de forma assíncrona:
    1. Tenta enfileirar via Redis/RQ na fila 'default' somente se houver workers ativos.
    2. Se não houver workers RQ ativos (cenário comum sem worker dedicado),
       executa em uma thread em background com app context.
    """
    try:
        from app.tasks.queue import get_queue, check_redis_health, get_redis_connection
        from rq import Worker
        if check_redis_health():
            conn = get_redis_connection()
            workers = Worker.all(connection=conn)
            active_default_workers = [w for w in workers if 'default' in [q.name for q in w.queues]]
            if active_default_workers:
                q = get_queue('default')
                q.enqueue(run_lead_scraper_task, job_id)
                logger.info(f"[Dispatch] Job ID {job_id} enfileirado com sucesso no Redis/RQ (fila: default, {len(active_default_workers)} workers)")
                return True
            else:
                logger.info("[Dispatch] Nenhum worker RQ ativo para a fila 'default'. Executando via background thread.")
    except Exception as e:
        logger.warning(f"[Dispatch] Falha ao verificar/enfileirar no RQ ({e}), utilizando thread de background...")

    # Fallback transparente para thread em segundo plano com o contexto da aplicação Flask
    from flask import current_app
    app = current_app._get_current_object()

    def run_in_thread(flask_app, j_id):
        with flask_app.app_context():
            run_lead_scraper_task(j_id)

    thread = threading.Thread(target=run_in_thread, args=(app, job_id), daemon=True)
    thread.start()
    logger.info(f"[Dispatch] Job ID {job_id} disparado com sucesso via background thread.")
    return True

