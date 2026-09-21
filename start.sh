#!/usr/bin/env bash

# ==============================================================================
# Script de Inicialização Orquestrada - CRM Pro (Gamificado)
# ==============================================================================

set -e

# Garante que o script roda a partir da pasta raiz do projeto
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# Cores para o terminal
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # Sem cor

echo -e "${BLUE}${BOLD}======================================================${NC}"
echo -e "${BLUE}${BOLD}        🚀 Inicializando o CRM Pro (Gamificado)       ${NC}"
echo -e "${BLUE}${BOLD}======================================================${NC}\n"

# 1. Verificar Docker
echo -e "${CYAN}[1/5] Verificando Docker e Docker Compose...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Erro: O comando 'docker' não foi encontrado. Instale o Docker para continuar.${NC}"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo -e "${RED}❌ Erro: O daemon do Docker não está rodando. Inicie o Docker Desktop ou o serviço docker.${NC}"
    exit 1
fi

# Detectar comando docker compose
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
elif command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE="docker-compose"
else
    echo -e "${RED}❌ Erro: Nem 'docker compose' nem 'docker-compose' foram encontrados.${NC}"
    exit 1
fi
echo -e "${GREEN}✔ Docker está ativo e pronto (${DOCKER_COMPOSE}).${NC}"

# 2. Subir containers Docker (WAHA, PostgreSQL, Redis)
echo -e "\n${CYAN}[2/5] Subindo serviços de mensageria no Docker (WAHA, Postgres, Redis)...${NC}"
$DOCKER_COMPOSE up -d

# Aguardar WAHA inicializar na porta 3000
echo -n -e "${YELLOW}Aguardando serviço WAHA responder na porta 3000...${NC}"
MAX_RETRIES=30
RETRY_COUNT=0
WAHA_READY=false

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/ &> /dev/null; then
        WAHA_READY=true
        break
    fi
    echo -n "."
    sleep 1
    RETRY_COUNT=$((RETRY_COUNT + 1))
done

echo ""
if [ "$WAHA_READY" = true ]; then
    echo -e "${GREEN}✔ Serviço WAHA online em http://localhost:3000${NC}"
else
    echo -e "${YELLOW}⚠ WAHA ainda está inicializando em segundo plano. Continuando...${NC}"
fi

# 3. Configurar e Ativar Ambiente Virtual Python
echo -e "\n${CYAN}[3/5] Verificando ambiente Python (venv)...${NC}"
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Criando ambiente virtual 'venv'...${NC}"
    python3 -m venv venv
fi

source venv/bin/activate
echo -e "${GREEN}✔ Ambiente virtual ativado ($(python --version)).${NC}"

# 4. Verificar dependências e Inicializar Banco de Dados
echo -e "\n${CYAN}[4/5] Verificando dependências e banco de dados...${NC}"

if ! python -c "import flask, flask_sqlalchemy" &> /dev/null; then
    echo -e "${YELLOW}Instalando dependências do requirements.txt...${NC}"
    pip install -r requirements.txt
else
    echo -e "${GREEN}✔ Dependências Python instaladas.${NC}"
fi

# Garante criação das tabelas e do usuário admin inicial
python init_db.py

# 5. Iniciar a Aplicação Flask
echo -e "\n${CYAN}[5/5] Iniciando o servidor web do CRM...${NC}"
echo -e "${GREEN}${BOLD}------------------------------------------------------${NC}"
echo -e "${GREEN}${BOLD} ✅ Sistema CRM Pro pronto para uso!                  ${NC}"
echo -e "${BOLD} 👉 Painel Web:${NC}     ${CYAN}http://localhost:5000${NC}"
echo -e "${BOLD} 👉 WAHA Dashboard:${NC} ${CYAN}http://localhost:3000${NC}"
echo -e "${BOLD} 🔑 Login Padrão:${NC}   Usuário: ${BOLD}admin${NC} | Senha: ${BOLD}admin123${NC}"
echo -e "${GREEN}${BOLD}------------------------------------------------------${NC}"
echo -e "${YELLOW}(Pressione Ctrl+C para encerrar o servidor Flask)${NC}\n"

cleanup() {
    echo -e "\n\n${YELLOW}Servidor Flask encerrado.${NC}"
    echo -n -e "Deseja parar também os containers Docker (WAHA, Postgres, Redis)? [s/N]: "
    read -r -t 10 response || response="n"
    if [[ "$response" =~ ^([sS][iI][mM]|[sS])$ ]]; then
        echo -e "${YELLOW}Parando containers Docker...${NC}"
        $DOCKER_COMPOSE stop
        echo -e "${GREEN}Containers parados com sucesso.${NC}"
    else
        echo -e "\n${BLUE}Containers continuam rodando em segundo plano.${NC}"
        echo -e "Para pará-los mais tarde, execute: ${BOLD}./stop.sh${NC}"
    fi
    exit 0
}

trap cleanup SIGINT SIGTERM

python run.py
