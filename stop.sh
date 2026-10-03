#!/usr/bin/env bash

# ==============================================================================
# Script para parar os serviços do CRM Pro (Containers Docker)
# ==============================================================================

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${YELLOW}${BOLD}Encerrando serviços do CRM Pro (Web e Docker)...${NC}"

# Finaliza servidores Flask e workers Python locais associados ao projeto
echo -e "${YELLOW}Finalizando processos locais do CRM (Flask / Workers)...${NC}"
pkill -f "python.*run.py" 2>/dev/null || true
pkill -f "python.*worker.py" 2>/dev/null || true
if command -v fuser &> /dev/null; then
    fuser -k 5000/tcp 2>/dev/null || true
fi

# Detectar comando docker compose
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
elif command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE="docker-compose"
else
    echo -e "${RED}❌ Erro: docker compose não encontrado.${NC}"
    exit 1
fi

$DOCKER_COMPOSE stop

echo -e "${GREEN}✔ Serviços do CRM Pro pausados com sucesso.${NC}"
echo -e "Dica: Para remover completamente os containers em vez de apenas pausar, use: ${BOLD}$DOCKER_COMPOSE down${NC}"
