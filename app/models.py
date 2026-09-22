from datetime import datetime
import uuid
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db, login

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    email = db.Column(db.String(120), index=True, unique=True)
    password_hash = db.Column(db.String(128))
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
    cpf = db.Column(db.String(14), unique=True, index=True)
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

    referred_by = db.relationship('User', foreign_keys=[referred_by_id], backref='referrals')

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
    channel = db.Column(db.String(32), default='whatsapp_link') # 'whatsapp_link', 'evolution_api'
    status = db.Column(db.String(32), default='sent') # 'sent', 'delivered', 'read', 'error'
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    api_response = db.Column(db.Text) # To store raw webhook/API json feedback
    waha_instance_id = db.Column(db.Integer, db.ForeignKey('waha_instance.id'), nullable=True)

    client = db.relationship('Client', backref='messages')
    user = db.relationship('User', backref='sent_messages')
    waha_instance = db.relationship('WahaInstance', backref='message_logs')

    def __repr__(self):
        return f'<MessageLog to {self.client_id} at {self.timestamp}>'
