import sys
import os

# Adiciona o diretório raiz ao path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models import Client, ScrapingJob, SystemLog
from app.utils.encoding import sanitize_encoding

def fix_all_encodings():
    app = create_app()
    with app.app_context():
        print("🔍 Verificando registros na base de dados para correção de caracteres...")

        clients = Client.query.all()
        repaired_clients = 0

        for client in clients:
            modified = False
            fields_to_check = ['name', 'address', 'notes', 'category', 'segment', 'website', 'data_usage_purpose', 'consent_channel']
            
            changes = {}
            for field in fields_to_check:
                val = getattr(client, field, None)
                if val and isinstance(val, str):
                    clean_val = sanitize_encoding(val)
                    if clean_val != val:
                        setattr(client, field, clean_val)
                        changes[field] = (val, clean_val)
                        modified = True

            if modified:
                repaired_clients += 1
                print(f"\n[Lead ID {client.id}]")
                for f, (old, new) in changes.items():
                    if f == 'notes':
                        print(f"  - {f}: texto de anotações corrigido")
                    else:
                        print(f"  - {f}: '{old}' -> '{new}'")

        # Verifica também scraping jobs
        jobs = ScrapingJob.query.all()
        repaired_jobs = 0
        for job in jobs:
            mod_job = False
            if job.query_term:
                clean_term = sanitize_encoding(job.query_term)
                if clean_term != job.query_term:
                    job.query_term = clean_term
                    mod_job = True
            if job.current_step:
                clean_step = sanitize_encoding(job.current_step)
                if clean_step != job.current_step:
                    job.current_step = clean_step
                    mod_job = True
            if mod_job:
                repaired_jobs += 1

        db.session.commit()
        print("\n" + "="*50)
        print(f"✅ Concluído com sucesso!")
        print(f"📊 Total de leads corrigidos: {repaired_clients}")
        print(f"📊 Total de jobs corrigidos: {repaired_jobs}")
        print("="*50)

if __name__ == '__main__':
    fix_all_encodings()
