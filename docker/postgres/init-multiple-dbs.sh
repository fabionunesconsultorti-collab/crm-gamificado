#!/bin/bash
set -e
set -u

# ==============================================================================
# Script de Inicialização de Múltiplos Bancos de Dados no PostgreSQL
# Executado automaticamente pelo entrypoint do container Postgres na primeira subida
# ==============================================================================

function create_database() {
    local database=$1
    echo "  [init-multiple-dbs] Verificando se o banco '$database' existe..."
    if ! psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tc "SELECT 1 FROM pg_database WHERE datname = '$database'" | grep -q 1; then
        echo "  [init-multiple-dbs] Criando banco de dados '$database' (owner: $POSTGRES_USER)..."
        psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE DATABASE \"$database\" OWNER \"$POSTGRES_USER\";"
        psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "GRANT ALL PRIVILEGES ON DATABASE \"$database\" TO \"$POSTGRES_USER\";"
        echo "  [init-multiple-dbs] Banco '$database' criado com sucesso!"
    else
        echo "  [init-multiple-dbs] Banco '$database' já existe. Ignorando criação."
    fi
}

if [ -n "${POSTGRES_MULTIPLE_DATABASES:-}" ]; then
    echo "[init-multiple-dbs] Inicializando múltiplos bancos de dados: $POSTGRES_MULTIPLE_DATABASES"
    for db in $(echo "$POSTGRES_MULTIPLE_DATABASES" | tr ',' ' '); do
        create_database "$db"
    done
    echo "[init-multiple-dbs] Todos os bancos foram configurados com sucesso!"
fi
