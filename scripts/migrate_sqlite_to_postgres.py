"""
Script de migração de dados de SQLite para PostgreSQL para o CRM Pro.
Uso:
    python scripts/migrate_sqlite_to_postgres.py [sqlite_path] [postgres_url]
Exemplo:
    python scripts/migrate_sqlite_to_postgres.py crm.db postgresql://waha_user:waha_password@localhost:5432/crm_db
"""

import os
import sys
from sqlalchemy import create_engine, MetaData, Table, text
from sqlalchemy.orm import sessionmaker

def migrate(sqlite_path="crm.db", pg_url=None):
    if not os.path.exists(sqlite_path):
        print(f"[-] Arquivo SQLite '{sqlite_path}' não encontrado. Nada a migrar.")
        return

    if not pg_url:
        pg_url = os.environ.get("DATABASE_URL")
        if not pg_url or "postgresql" not in pg_url:
            pg_user = os.environ.get("POSTGRES_USER", "waha_user")
            pg_pass = os.environ.get("POSTGRES_PASSWORD", "waha_password")
            pg_host = os.environ.get("POSTGRES_HOST", "localhost")
            pg_port = os.environ.get("POSTGRES_PORT", "5432")
            pg_db = os.environ.get("POSTGRES_DB", "crm_db")
            pg_url = f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"

    print(f"[*] Origem SQLite: sqlite:///{os.path.abspath(sqlite_path)}")
    print(f"[*] Destino PostgreSQL: {pg_url}")

    src_engine = create_engine(f"sqlite:///{os.path.abspath(sqlite_path)}")
    dst_engine = create_engine(pg_url)

    src_meta = MetaData()
    src_meta.reflect(bind=src_engine)

    dst_meta = MetaData()
    dst_meta.reflect(bind=dst_engine)

    # Ordenar tabelas respeitando chaves estrangeiras se possível
    tables_to_migrate = [t for t in src_meta.sorted_tables if t.name in dst_meta.tables]

    with dst_engine.connect() as dst_conn:
        trans = dst_conn.begin()
        try:
            for table in tables_to_migrate:
                table_name = table.name
                if table_name == 'alembic_version':
                    continue

                print(f"[>] Migrando tabela: {table_name}...")
                with src_engine.connect() as src_conn:
                    rows = src_conn.execute(table.select()).mappings().all()

                if not rows:
                    print(f"    (0 registros)")
                    continue

                dst_table = dst_meta.tables[table_name]
                dst_conn.execute(dst_table.insert(), [dict(r) for r in rows])
                print(f"    -> {len(rows)} registros inseridos com sucesso.")

                # Resetar sequence do ID no PostgreSQL se existir coluna id
                if 'id' in dst_table.c:
                    seq_check = dst_conn.execute(text(f"SELECT pg_get_serial_sequence('{table_name}', 'id');")).scalar()
                    if seq_check:
                        dst_conn.execute(text(f"SELECT setval('{seq_check}', COALESCE((SELECT MAX(id) FROM {table_name}), 1));"))

            trans.commit()
            print("[+] Migração de dados concluída com sucesso!")
        except Exception as e:
            trans.rollback()
            print(f"[!] Erro durante migração: {e}")
            raise

if __name__ == "__main__":
    sqlite_file = sys.argv[1] if len(sys.argv) > 1 else "crm.db"
    postgres_uri = sys.argv[2] if len(sys.argv) > 2 else None
    migrate(sqlite_file, postgres_uri)
