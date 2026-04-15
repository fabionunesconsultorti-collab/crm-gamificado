from app import create_app, db
from app.models import User

app = create_app()

with app.app_context():
    db.create_all()
    
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
