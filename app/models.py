from datetime import datetime
import uuid
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db, login

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    email = db.Column(db.String(120), index=True, unique=True)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(20), default='vendedor') # 'admin', 'gerente', 'vendedor'
    performance_points = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

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
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    api_response = db.Column(db.Text) # To store raw webhook/API json feedback
    waha_instance_id = db.Column(db.Integer, db.ForeignKey('waha_instance.id'), nullable=True)

    client = db.relationship('Client', backref='messages')
    user = db.relationship('User', backref='sent_messages')
    waha_instance = db.relationship('WahaInstance', backref='message_logs')

    def __repr__(self):
        return f'<MessageLog to {self.client_id} at {self.timestamp}>'

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


