from datetime import datetime
import uuid
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db, login

import json

class PermissionGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.String(256))
    permissions_json = db.Column(db.Text, default='{}')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_permissions(self) -> dict:
        try:
            return json.loads(self.permissions_json) if self.permissions_json else {}
        except Exception:
            return {}

    def set_permissions(self, perm_dict: dict):
        self.permissions_json = json.dumps(perm_dict)

    def __repr__(self):
        return f'<PermissionGroup {self.name}>'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    email = db.Column(db.String(120), index=True, unique=True)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(20), default='vendedor') # 'admin', 'gerente', 'vendedor'
    group_id = db.Column(db.Integer, db.ForeignKey('permission_group.id'), nullable=True)
    custom_permissions_json = db.Column(db.Text, default='{}')
    performance_points = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    group = db.relationship('PermissionGroup', backref=db.backref('users', lazy=True))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_custom_permissions(self) -> dict:
        try:
            return json.loads(self.custom_permissions_json) if self.custom_permissions_json else {}
        except Exception:
            return {}

    def set_custom_permissions(self, perm_dict: dict):
        self.custom_permissions_json = json.dumps(perm_dict)

    def has_permission(self, resource: str, action: str) -> bool:
        """
        Verifica se o usuário possui a permissão (resource.action) respeitando:
        1. Sobrescrita Individual (custom_permissions do usuário).
        2. Herdada do Grupo de Permissões (group.permissions).
        3. Fallbacks de papel e segurança (view, edit, delete).
        """
        perm_key = f"{resource}.{action}"
        
        # 1. Sobrescrita individual do Usuário
        custom_perms = self.get_custom_permissions()
        if perm_key in custom_perms:
            return bool(custom_perms[perm_key])

        # 2. Grupo atribuído
        if self.group:
            group_perms = self.group.get_permissions()
            if perm_key in group_perms:
                return bool(group_perms[perm_key])

        # 3. Fallback legado por role
        if self.role == 'admin':
            return True
        if self.role == 'gerente' and action != 'delete':
            return True

        if resource in ['clients', 'kanban'] and action in ['view', 'edit']:
            return True

        return False

    def __repr__(self):
        return f'<User {self.username}>'

@login.user_loader
def load_user(id):
    return User.query.get(int(id))

class Store(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), index=True)
    
    clients = db.relationship('Client', backref='preferred_store', lazy='dynamic')

    def __repr__(self):
        return f'<Store {self.name}>'

class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, index=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(128), index=True)
    phone = db.Column(db.String(20), index=True, unique=True)
    email = db.Column(db.String(120), index=True)
    status = db.Column(db.String(64), default='lead') # lead, contato, proposta, fechado, perdido
    notes = db.Column(db.Text)
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 1. Campos Essenciais (Operação e Fiscal)
    cpf = db.Column(db.String(32), unique=True, index=True) # Suporta CPF (11/14 chars) e CNPJ (14/18 chars)
    cep = db.Column(db.String(10))
    address = db.Column(db.String(256))
    birth_date = db.Column(db.Date)
    
    # 2. Estratégicos e Comportamentais
    gender = db.Column(db.String(20))
    preferred_store_id = db.Column(db.Integer, db.ForeignKey('store.id'))
    referred_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    preferred_channel = db.Column(db.String(30))
    lead_source = db.Column(db.String(64))
    last_purchase_date = db.Column(db.Date)
    purchase_frequency = db.Column(db.Integer, default=0)
    ltv = db.Column(db.Float, default=0.0)

    # 3. Fidelidade e Engajamento
    loyalty_points = db.Column(db.Float, default=0.0)
    tier = db.Column(db.String(30), default='bronze')
    points_expiration = db.Column(db.Date)
    badges = db.Column(db.Text) # CSV or JSON string
    
    # 4. Conformidade LGPD
    opt_in = db.Column(db.Boolean, default=False)
    opt_in_date = db.Column(db.DateTime)
    data_usage_purpose = db.Column(db.String(256))
    consent_channel = db.Column(db.String(128))

    # 5. Prospecção Ativa (Google Maps / Outbound) & Presença Digital
    website = db.Column(db.Text)
    instagram = db.Column(db.String(256))
    category = db.Column(db.String(256))
    segment = db.Column(db.String(256))
    google_rating = db.Column(db.Float, default=0.0)
    google_reviews_count = db.Column(db.Integer, default=0)

    assigned_user = db.relationship('User', foreign_keys=[assigned_to], backref='assigned_clients')
    referred_by = db.relationship('User', foreign_keys=[referred_by_id], backref='referrals')

    @property
    def display_segment(self):
        """Retorna o segmento prioritário ou categoria da prospecção."""
        return (self.segment or self.category or '').strip()

    @property
    def instagram_url(self):
        """Retorna a URL completa para o Instagram do cliente se preenchido."""
        if not self.instagram:
            return None
        handle = self.instagram.strip()
        if handle.startswith(('http://', 'https://')):
            return handle
        handle = handle.lstrip('@')
        return f"https://instagram.com/{handle}"

    @property
    def website_url(self):
        """Retorna a URL do website garantindo protocolo http/https."""
        if not self.website:
            return None
        url = self.website.strip()
        if not url.startswith(('http://', 'https://')):
            return f"https://{url}"
        return url
    @property
    def clean_phone(self):
        """Retorna apenas os dígitos do telefone."""
        if not self.phone:
            return ""
        return ''.join(filter(str.isdigit, str(self.phone)))

    @property
    def formatted_phone(self):
        """Retorna o telefone formatado visualmente no padrão brasileiro (DD) 9XXXX-XXXX."""
        if not self.phone:
            return ""
        try:
            from app.utils.lead_enricher import LeadEnricher
            return LeadEnricher.format_phone_display(self.phone)
        except Exception:
            return str(self.phone)

    @property
    def whatsapp_url(self):
        """Retorna a URL do wa.me garantindo DDI 55 único e formatação correta sem duplicações."""
        if not self.phone:
            return None
        try:
            from app.utils.lead_enricher import LeadEnricher
            return LeadEnricher.to_whatsapp_url(self.phone)
        except Exception:
            digits = ''.join(filter(str.isdigit, str(self.phone)))
            if not digits:
                return None
            if len(digits) in (10, 11):
                return f"https://wa.me/55{digits}"
            return f"https://wa.me/{digits}"

    @property
    def whatsapp_chat_id(self):
        """Retorna o chat_id no padrão WAHA (ex: 5519998306652@c.us)."""
        if not self.phone:
            return None
        try:
            from app.utils.lead_enricher import LeadEnricher
            e164 = LeadEnricher.to_e164(self.phone)
            return f"{e164}@c.us" if e164 else None
        except Exception:
            digits = ''.join(filter(str.isdigit, str(self.phone)))
            if not digits:
                return None
            if len(digits) in (10, 11):
                return f"55{digits}@c.us"
            return f"{digits}@c.us"

    def __repr__(self):
        return f'<Client {self.name}>'

class SystemLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    action = db.Column(db.String(256))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='logs')

class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, index=True)
    value = db.Column(db.Text)
    description = db.Column(db.String(256))

    @classmethod
    def get_val(cls, key, default=None):
        s = cls.query.filter_by(key=key).first()
        return s.value if s and s.value is not None else default

    @classmethod
    def set_val(cls, key, value, description=None):
        s = cls.query.filter_by(key=key).first()
        if not s:
            s = cls(key=key, value=value, description=description)
            db.session.add(s)
        else:
            s.value = value
            if description:
                s.description = description
        db.session.commit()
        return s

    set = set_val
    get = get_val

    def __repr__(self):
        return f'<Setting {self.key}>'


class MessageTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), index=True, unique=True)
    text_content = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<MessageTemplate {self.name}>'

class WahaInstance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128)) # Friendly name e.g. "Server 1" or "Atendimento"
    api_url = db.Column(db.String(256))
    api_key = db.Column(db.String(128))
    session_name = db.Column(db.String(128), default='default')
    is_default = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(64), default='disconnected')

    # Anti-ban e Rate Limiting
    enable_anti_ban = db.Column(db.Boolean, default=True)
    min_delay_seconds = db.Column(db.Integer, default=5)
    max_delay_seconds = db.Column(db.Integer, default=15)
    max_messages_per_hour = db.Column(db.Integer, default=80)
    max_messages_per_day = db.Column(db.Integer, default=500)
    
    # Horário de Silêncio (Quiet Hours)
    quiet_hours_enabled = db.Column(db.Boolean, default=False)
    quiet_hours_start = db.Column(db.String(5), default='22:00')
    quiet_hours_end = db.Column(db.String(5), default='08:00')

    # Modo Aquecimento (Warm-up de Chip Novo)
    warmup_mode = db.Column(db.Boolean, default=False)
    warmup_start_date = db.Column(db.DateTime, nullable=True)

    # Contadores e timestamps
    hourly_count = db.Column(db.Integer, default=0)
    daily_count = db.Column(db.Integer, default=0)
    last_sent_at = db.Column(db.DateTime, nullable=True)

    def reset_counters_if_needed(self, current_dt=None):
        if not self.last_sent_at:
            return
        now = current_dt or datetime.utcnow()
        if now.date() != self.last_sent_at.date() or (now - self.last_sent_at).total_seconds() >= 86400:
            self.daily_count = 0
            self.hourly_count = 0
        elif now.hour != self.last_sent_at.hour or (now - self.last_sent_at).total_seconds() >= 3600:
            self.hourly_count = 0

    def get_effective_daily_limit(self):
        max_day = self.max_messages_per_day if self.max_messages_per_day is not None else 500
        if not self.warmup_mode:
            return max_day
        
        start_date = self.warmup_start_date or datetime.utcnow()
        days_passed = max(1, (datetime.utcnow().date() - start_date.date()).days + 1)
        
        warmup_schedule = {
            1: 20,
            2: 40,
            3: 70,
            4: 110,
            5: 160,
            6: 220,
            7: 300
        }
        if days_passed in warmup_schedule:
            warmup_limit = warmup_schedule[days_passed]
        else:
            warmup_limit = min(max_day, 300 + (days_passed - 7) * 80)
            
        return min(max_day, warmup_limit)

    def is_in_quiet_hours(self, current_time_str=None):
        if not self.quiet_hours_enabled:
            return False
        if not self.quiet_hours_start or not self.quiet_hours_end:
            return False
        
        now_str = current_time_str if current_time_str else datetime.now().strftime('%H:%M')
        start = self.quiet_hours_start
        end = self.quiet_hours_end
        
        if start <= end:
            return start <= now_str < end
        else:
            return now_str >= start or now_str < end

    def check_anti_ban_limits(self, ignore_quiet_hours=False):
        self.reset_counters_if_needed()
        stats = self.get_anti_ban_stats()
        
        if not self.enable_anti_ban:
            return True, "Anti-ban desativado", stats
            
        if not ignore_quiet_hours and self.is_in_quiet_hours():
            reason = f"Horário de silêncio ativo ({self.quiet_hours_start} às {self.quiet_hours_end}). Disparos pausados para evitar denúncias."
            stats['can_send'] = False
            stats['block_reason'] = reason
            stats['reason_code'] = 'quiet_hours'
            return False, reason, stats
            
        effective_daily = self.get_effective_daily_limit()
        if (self.daily_count or 0) >= effective_daily:
            mode_txt = " (Modo Aquecimento)" if self.warmup_mode else ""
            reason = f"Limite diário{mode_txt} atingido ({self.daily_count}/{effective_daily} msgs). Envio pausado por proteção anti-ban."
            stats['can_send'] = False
            stats['block_reason'] = reason
            stats['reason_code'] = 'daily_limit'
            return False, reason, stats
            
        max_hour = self.max_messages_per_hour if self.max_messages_per_hour is not None else 80
        if (self.hourly_count or 0) >= max_hour:
            reason = f"Limite por hora atingido ({self.hourly_count}/{max_hour} msgs). Aguarde a próxima hora para retomar os disparos."
            stats['can_send'] = False
            stats['block_reason'] = reason
            stats['reason_code'] = 'hourly_limit'
            return False, reason, stats
            
        return True, "OK", stats

    def record_message_sent(self):
        self.reset_counters_if_needed()
        self.hourly_count = (self.hourly_count or 0) + 1
        self.daily_count = (self.daily_count or 0) + 1
        self.last_sent_at = datetime.utcnow()

    def get_anti_ban_stats(self):
        self.reset_counters_if_needed()
        effective_daily = self.get_effective_daily_limit()
        start_date = self.warmup_start_date or datetime.utcnow()
        warmup_day = max(1, (datetime.utcnow().date() - start_date.date()).days + 1) if self.warmup_mode else None
        
        in_quiet = self.is_in_quiet_hours()
        can_send = True
        block_reason = None
        reason_code = None
        
        max_hour = self.max_messages_per_hour if self.max_messages_per_hour is not None else 80
        if self.enable_anti_ban:
            if in_quiet:
                can_send = False
                block_reason = f"Horário de silêncio ({self.quiet_hours_start} às {self.quiet_hours_end})"
                reason_code = 'quiet_hours'
            elif (self.daily_count or 0) >= effective_daily:
                can_send = False
                block_reason = f"Limite diário atingido ({self.daily_count}/{effective_daily})"
                reason_code = 'daily_limit'
            elif (self.hourly_count or 0) >= max_hour:
                can_send = False
                block_reason = f"Limite por hora atingido ({self.hourly_count}/{max_hour})"
                reason_code = 'hourly_limit'

        return {
            'instance_id': self.id,
            'name': self.name,
            'enable_anti_ban': bool(self.enable_anti_ban),
            'min_delay_seconds': self.min_delay_seconds if self.min_delay_seconds is not None else 5,
            'max_delay_seconds': self.max_delay_seconds if self.max_delay_seconds is not None else 15,
            'max_messages_per_hour': max_hour,
            'hourly_count': self.hourly_count or 0,
            'max_messages_per_day': self.max_messages_per_day if self.max_messages_per_day is not None else 500,
            'effective_daily_limit': effective_daily,
            'daily_count': self.daily_count or 0,
            'quiet_hours_enabled': bool(self.quiet_hours_enabled),
            'quiet_hours_start': self.quiet_hours_start or '22:00',
            'quiet_hours_end': self.quiet_hours_end or '08:00',
            'is_in_quiet_hours': in_quiet,
            'warmup_mode': bool(self.warmup_mode),
            'warmup_day': warmup_day,
            'warmup_start_date': self.warmup_start_date.strftime('%Y-%m-%d') if self.warmup_start_date else None,
            'can_send': can_send,
            'block_reason': block_reason,
            'reason_code': reason_code,
            'last_sent_at': self.last_sent_at.strftime('%d/%m/%Y %H:%M:%S') if self.last_sent_at else None
        }

    def __repr__(self):
        return f'<WahaInstance {self.name}>'

class FileMappingTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), index=True)
    target_module = db.Column(db.String(64)) # e.g. 'clients' or 'bulk'
    mapping_data = db.Column(db.Text) # JSON serialized
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='mapping_templates')

    def __repr__(self):
        return f'<FileMappingTemplate {self.name}>'

class MessageLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text)
    channel = db.Column(db.String(32), default='whatsapp_link') # 'whatsapp_link', 'waha_api'
    status = db.Column(db.String(32), default='sent') # 'sent', 'delivered', 'read', 'error'
    direction = db.Column(db.String(16), default='outbound') # 'inbound', 'outbound'
    chat_id = db.Column(db.String(64), index=True, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    api_response = db.Column(db.Text) # To store raw webhook/API json feedback
    waha_instance_id = db.Column(db.Integer, db.ForeignKey('waha_instance.id'), nullable=True)

    client = db.relationship('Client', backref='messages')
    user = db.relationship('User', backref='sent_messages')
    waha_instance = db.relationship('WahaInstance', backref='message_logs')

    def __repr__(self):
        return f'<MessageLog {self.direction} to/from {self.client_id or self.chat_id} at {self.timestamp}>'

class ScrapingJob(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, index=True, default=lambda: str(uuid.uuid4()))
    query_term = db.Column(db.String(256), nullable=False)
    depth = db.Column(db.Integer, default=1)
    extract_emails = db.Column(db.Boolean, default=True)
    status = db.Column(db.String(32), default='queued') # queued, processing, completed, failed
    total_scraped = db.Column(db.Integer, default=0)
    total_imported = db.Column(db.Integer, default=0)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    external_job_id = db.Column(db.String(128), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    progress = db.Column(db.Integer, default=0)
    current_step = db.Column(db.String(128), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime, nullable=True)

    created_by = db.relationship('User', backref='scraping_jobs')

    def __init__(self, **kwargs):
        if 'query' in kwargs and 'query_term' not in kwargs:
            kwargs['query_term'] = kwargs.pop('query')
        super().__init__(**kwargs)

    def to_dict(self):
        elapsed = 0
        if self.created_at:
            end = self.finished_at or datetime.utcnow()
            elapsed = max(0, int((end - self.created_at).total_seconds()))

        return {
            'id': self.id,
            'public_id': self.public_id,
            'query': self.query_term,
            'query_term': self.query_term,
            'depth': self.depth,
            'extract_emails': self.extract_emails,
            'status': self.status,
            'progress': self.progress if self.progress is not None else 0,
            'current_step': self.current_step or '',
            'elapsed_seconds': elapsed,
            'total_scraped': self.total_scraped or 0,
            'total_imported': self.total_imported or 0,
            'created_by': self.created_by.username if self.created_by else 'Sistema',
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else None,
            'finished_at': self.finished_at.strftime('%d/%m/%Y %H:%M') if self.finished_at else None,
            'error_message': self.error_message
        }

    def __repr__(self):
        return f'<ScrapingJob {self.id}: {self.query_term} [{self.status}]>'


class KnowledgeDoc(db.Model):
    __tablename__ = 'knowledge_doc'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(64), default='geral')  # 'faq', 'precos', 'servicos', 'institucional'
    doc_type = db.Column(db.String(32), default='text')   # 'text', 'faq', 'pdf', 'url'
    content = db.Column(db.Text, nullable=False)
    chunks_count = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'category': self.category,
            'doc_type': self.doc_type,
            'content': self.content,
            'chunks_count': self.chunks_count,
            'is_active': self.is_active,
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else '',
            'updated_at': self.updated_at.strftime('%d/%m/%Y %H:%M') if self.updated_at else ''
        }

    def __repr__(self):
        return f'<KnowledgeDoc {self.id}: {self.title} [{self.category}]>'


class IntegrationConfig(db.Model):
    __tablename__ = 'integration_config'

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(64), unique=True, index=True, nullable=False)  # ex: 'bling', 'tiny'
    name = db.Column(db.String(128), nullable=False)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    auth_type = db.Column(db.String(32), default='oauth2')  # 'oauth2', 'api_key'
    client_id = db.Column(db.String(256), nullable=True)
    client_secret = db.Column(db.String(256), nullable=True)
    api_key = db.Column(db.String(256), nullable=True)
    access_token = db.Column(db.Text, nullable=True)
    refresh_token = db.Column(db.Text, nullable=True)
    token_expires_at = db.Column(db.DateTime, nullable=True)
    settings_json = db.Column(db.Text, default='{}')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_settings(self):
        import json
        if not self.settings_json:
            return {}
        try:
            return json.loads(self.settings_json)
        except Exception:
            return {}

    def set_settings(self, data_dict):
        import json
        self.settings_json = json.dumps(data_dict)

    def to_dict(self):
        return {
            'id': self.id,
            'provider': self.provider,
            'name': self.name,
            'is_active': bool(self.is_active),
            'auth_type': self.auth_type,
            'client_id': self.client_id or '',
            'has_client_secret': bool(self.client_secret),
            'has_api_key': bool(self.api_key),
            'has_access_token': bool(self.access_token),
            'token_expires_at': self.token_expires_at.strftime('%Y-%m-%d %H:%M:%S') if self.token_expires_at else None,
            'settings': self.get_settings(),
            'updated_at': self.updated_at.strftime('%d/%m/%Y %H:%M') if self.updated_at else ''
        }

    def __repr__(self):
        return f'<IntegrationConfig {self.provider} active={self.is_active}>'


class ExternalEntityMap(db.Model):
    __tablename__ = 'external_entity_map'

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(64), index=True, nullable=False)  # ex: 'bling'
    crm_entity_type = db.Column(db.String(32), index=True, nullable=False)  # ex: 'client'
    crm_entity_id = db.Column(db.Integer, index=True, nullable=False)  # ID local
    external_id = db.Column(db.String(128), index=True, nullable=False)  # ID no Bling
    sync_status = db.Column(db.String(32), default='synced')  # 'synced', 'pending', 'error'
    last_synced_at = db.Column(db.DateTime, default=datetime.utcnow)
    sync_hash = db.Column(db.String(64), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('provider', 'crm_entity_type', 'crm_entity_id', name='uq_provider_entity_local'),
        db.UniqueConstraint('provider', 'crm_entity_type', 'external_id', name='uq_provider_entity_ext'),
    )

    def __repr__(self):
        return f'<ExternalEntityMap {self.provider}:{self.crm_entity_type} {self.crm_entity_id}<->{self.external_id}>'


class BlingSalesCache(db.Model):
    __tablename__ = 'bling_sales_cache'

    id = db.Column(db.Integer, primary_key=True)
    bling_order_id = db.Column(db.String(128), unique=True, index=True, nullable=False)
    order_number = db.Column(db.String(64))
    client_cpf_cnpj = db.Column(db.String(32), index=True)
    client_name = db.Column(db.String(256))
    total_value = db.Column(db.Float, default=0.0)
    order_date = db.Column(db.Date)
    status = db.Column(db.String(64), index=True)
    seller_name = db.Column(db.String(128))
    raw_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'bling_order_id': self.bling_order_id,
            'order_number': self.order_number,
            'client_cpf_cnpj': self.client_cpf_cnpj,
            'client_name': self.client_name,
            'total_value': self.total_value or 0.0,
            'order_date': self.order_date.strftime('%d/%m/%Y') if self.order_date else '',
            'status': self.status or '',
            'seller_name': self.seller_name or '',
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else ''
        }

    def __repr__(self):
        return f'<BlingSalesCache {self.order_number} ({self.total_value})>'


class IntegrationLog(db.Model):
    __tablename__ = 'integration_log'

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(64), index=True, nullable=False)
    action = db.Column(db.String(128), nullable=False)
    status = db.Column(db.String(32), default='info')  # 'success', 'warning', 'error', 'info'
    details = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<IntegrationLog {self.provider}:{self.action} [{self.status}] at {self.timestamp}>'


class BlingProductCache(db.Model):
    __tablename__ = 'bling_product_cache'

    id = db.Column(db.Integer, primary_key=True)
    bling_product_id = db.Column(db.String(128), unique=True, index=True, nullable=False)
    code = db.Column(db.String(64), index=True)
    name = db.Column(db.String(256), index=True)
    brand = db.Column(db.String(128), index=True)
    supplier_name = db.Column(db.String(128), index=True)
    category = db.Column(db.String(128), index=True)
    size = db.Column(db.String(32), index=True)
    price = db.Column(db.Float, default=0.0)
    cost_price = db.Column(db.Float, default=0.0)
    current_stock = db.Column(db.Integer, default=0)
    last_sale_date = db.Column(db.Date, nullable=True)
    days_without_sale = db.Column(db.Integer, default=0)
    raw_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'bling_product_id': self.bling_product_id,
            'code': self.code or '',
            'name': self.name or '',
            'brand': self.brand or 'Não Informada',
            'supplier_name': self.supplier_name or 'Não Informado',
            'category': self.category or 'Geral',
            'size': self.size or 'Único',
            'price': self.price or 0.0,
            'cost_price': self.cost_price or 0.0,
            'current_stock': self.current_stock or 0,
            'last_sale_date': self.last_sale_date.strftime('%d/%m/%Y') if self.last_sale_date else 'Sem Vendas',
            'days_without_sale': self.days_without_sale or 0,
            'capital_locked': round((self.current_stock or 0) * (self.cost_price or self.price or 0.0), 2)
        }

    def __repr__(self):
        return f'<BlingProductCache {self.code}:{self.name} stock={self.current_stock}>'


class BulkCampaign(db.Model):
    __tablename__ = 'bulk_campaign'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    status = db.Column(db.String(32), default='draft', index=True) # draft, running, paused, completed, cancelled
    message_text = db.Column(db.Text, nullable=False)
    
    waha_instance_id = db.Column(db.Integer, db.ForeignKey('waha_instance.id'), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    template_id = db.Column(db.Integer, db.ForeignKey('message_template.id'), nullable=True)
    
    # Parâmetros de Anti-Spam e Cadência
    min_delay = db.Column(db.Integer, default=6)
    max_delay = db.Column(db.Integer, default=16)
    batch_pause_every = db.Column(db.Integer, default=25)
    batch_pause_duration = db.Column(db.Integer, default=60)
    use_ai = db.Column(db.Boolean, default=False)
    use_spintax = db.Column(db.Boolean, default=True)

    # Telemetria e Contadores
    total_count = db.Column(db.Integer, default=0)
    processed_count = db.Column(db.Integer, default=0)
    success_count = db.Column(db.Integer, default=0)
    error_count = db.Column(db.Integer, default=0)
    consecutive_errors = db.Column(db.Integer, default=0)
    circuit_breaker_triggered = db.Column(db.Boolean, default=False)
    pause_reason = db.Column(db.String(256), nullable=True)
    filter_criteria_json = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Relacionamentos
    waha_instance = db.relationship('WahaInstance', backref='campaigns')
    created_by = db.relationship('User', backref='created_campaigns')
    template = db.relationship('MessageTemplate', backref='campaigns')
    recipients = db.relationship('BulkCampaignRecipient', backref='campaign', cascade='all, delete-orphan', lazy='dynamic')

    @property
    def progress_pct(self):
        if not self.total_count or self.total_count == 0:
            return 0
        return min(100, int((self.processed_count / self.total_count) * 100))

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'status': self.status,
            'message_text': self.message_text,
            'waha_instance_id': self.waha_instance_id,
            'waha_instance_name': self.waha_instance.name if self.waha_instance else 'Padrão',
            'min_delay': self.min_delay,
            'max_delay': self.max_delay,
            'use_ai': self.use_ai,
            'use_spintax': self.use_spintax,
            'total_count': self.total_count,
            'processed_count': self.processed_count,
            'success_count': self.success_count,
            'error_count': self.error_count,
            'consecutive_errors': self.consecutive_errors,
            'circuit_breaker_triggered': self.circuit_breaker_triggered,
            'pause_reason': self.pause_reason,
            'progress_pct': self.progress_pct,
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else None,
            'started_at': self.started_at.strftime('%d/%m/%Y %H:%M') if self.started_at else None,
            'completed_at': self.completed_at.strftime('%d/%m/%Y %H:%M') if self.completed_at else None
        }

    def __repr__(self):
        return f'<BulkCampaign {self.id}:{self.name} [{self.status}]>'


class BulkCampaignRecipient(db.Model):
    __tablename__ = 'bulk_campaign_recipient'

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('bulk_campaign.id', ondelete='CASCADE'), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id', ondelete='SET NULL'), nullable=True, index=True)
    name = db.Column(db.String(128), default='')
    phone = db.Column(db.String(32), nullable=False, index=True)
    source = db.Column(db.String(32), default='crm') # crm, manual, file
    status = db.Column(db.String(32), default='pending', index=True) # pending, processing, sent, failed, cancelled, skipped
    custom_vars_json = db.Column(db.Text, nullable=True)
    resolved_message = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.String(256), nullable=True)
    waha_message_id = db.Column(db.String(128), nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    attempts = db.Column(db.Integer, default=0)

    client = db.relationship('Client')

    def to_dict(self):
        return {
            'id': self.id,
            'campaign_id': self.campaign_id,
            'client_id': self.client_id,
            'name': self.name,
            'phone': self.phone,
            'source': self.source,
            'status': self.status,
            'resolved_message': self.resolved_message,
            'error_message': self.error_message,
            'sent_at': self.sent_at.strftime('%d/%m/%Y %H:%M:%S') if self.sent_at else None
        }

    def __repr__(self):
        return f'<BulkCampaignRecipient {self.id}:{self.phone} [{self.status}]>'


class FineTuningPair(db.Model):
    """
    Par de Diálogo Curado para Aprendizado Contínuo e Fine-Tuning do Bot:
    - Captura o que o contato perguntou/enviou (Lead Prompt)
    - Captura o que o operador humano respondeu no WhatsApp (Human Response - Padrão Ouro)
    - Rascunho que a IA havia gerado (Bot Draft)
    - Classificações do TensorFlow (Intenção e Sentimento)
    - Curadoria Humana: status 'pending', 'approved', 'rejected'
    - Retroalimentação RAG: promovido a documento do ChromaDB / KnowledgeDoc
    """
    __tablename__ = 'finetuning_pair'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=True)
    chat_id = db.Column(db.String(64), index=True, nullable=False)
    lead_prompt = db.Column(db.Text, nullable=False)
    bot_draft = db.Column(db.Text, nullable=True)
    human_response = db.Column(db.Text, nullable=True)
    intent_detected = db.Column(db.String(64), nullable=True)
    sentiment_detected = db.Column(db.String(64), nullable=True)
    status = db.Column(db.String(32), default='pending')  # 'pending', 'approved', 'rejected'
    quality_score = db.Column(db.Integer, default=5)       # 1 a 5
    is_in_rag = db.Column(db.Boolean, default=False)
    knowledge_doc_id = db.Column(db.Integer, db.ForeignKey('knowledge_doc.id'), nullable=True)
    source = db.Column(db.String(32), default='waha_capture')  # 'waha_capture', 'manual', 'import'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = db.relationship('Client', backref='finetuning_pairs')
    knowledge_doc = db.relationship('KnowledgeDoc', backref='finetuning_pairs')

    def to_dict(self):
        return {
            'id': self.id,
            'client_id': self.client_id,
            'client_name': self.client.name if self.client else None,
            'chat_id': self.chat_id,
            'lead_prompt': self.lead_prompt,
            'bot_draft': self.bot_draft,
            'human_response': self.human_response,
            'intent_detected': self.intent_detected,
            'sentiment_detected': self.sentiment_detected,
            'status': self.status,
            'quality_score': self.quality_score,
            'is_in_rag': self.is_in_rag,
            'knowledge_doc_id': self.knowledge_doc_id,
            'source': self.source,
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else '',
            'updated_at': self.updated_at.strftime('%d/%m/%Y %H:%M') if self.updated_at else ''
        }

    def __repr__(self):
        return f'<FineTuningPair {self.id}: {self.chat_id} [{self.status}]>'






