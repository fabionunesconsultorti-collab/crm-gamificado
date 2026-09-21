# CRM Pro (Gamificado)

Um sistema web responsivo e completo para gerenciamento inteligente de clientes (CRM), gestão de funil de vendas (Kanban) e automação de mensageria com foco na integração via WhatsApp. O sistema inclui rastreamento de fidelidade (XP e Níveis) que engaja equipes comerciais e aprimora a visão da jornada do cliente.

## 🚀 Principais Funcionalidades

- **Gestão de Clientes (CRM):** CRUD completo de clientes com segmentação por níveis (Tier) e pontuação de fidelidade (XP).
- **Funil de Vendas (Kanban):** Visualização dinâmica e interativa (drag-n-drop) das oportunidades e etapas de vendas.
- **Automação de Mensageria (WhatsApp):** Integração via WAHA API (WhatsApp HTTP API) embutida para disparos sem depender do navegador.
- **Templates Dinâmicos:** Criação e uso de templates de mensagens com interpolação de variáveis (ex: `[NOME]`, `[DATA]`, `[VENDEDOR]`).
- **Importação Massiva:** Ferramenta para importação de clientes e dados via arquivos CSV e Excel, com suporte a mapeamento de colunas.
- **Integração com IA (Gemini):** Funcionalidade para personalização e reescrita inteligente de mensagens utilizando o poder da IA generativa do Google.
- **Logs e Tracking:** Rastreamento de envio de mensagens e interações, registrando histórico completo de sucesso e autoria.

## 🛠 Tecnologias Utilizadas

- **Backend:** Python 3.12, Flask, Flask-SQLAlchemy, Flask-Migrate
- **Banco de Dados (Aplicação):** SQLite (fácil distribuição e setup inicial)
- **Frontend:** HTML5, Vanilla JS, CSS Customizado focado em "Glassmorphism"
- **Integrações:** WAHA API (WhatsApp) com PostgreSQL + Redis via Docker, Google Generative AI (Gemini SDK)

---

## 💻 Como Executar em um Novo Ambiente

### ⚡ Inicialização Rápida (Recomendado no Linux/macOS)
Execute o script orquestrador que configura o ambiente, sobe os containers Docker e inicia o Flask automaticamente:
```bash
./start.sh
```
Para pausar os serviços do Docker posteriormente:
```bash
./stop.sh
```

---

### 1. Pré-requisitos

- **Python 3.12+** instalado.
- **Git** (para versionamento e clonagem).
- **Docker Desktop e Docker Compose** instalados e em execução (necessário para rodar o serviço WAHA de WhatsApp localmente).

### 2. Configuração Inicial e Ambiente Virtual

Abra o terminal e acesse a pasta do projeto:

```bash
cd crm-gamificado
# ou o diretório raiz equivalente (ex: cd CRM)
```

Crie um ambiente virtual (recomendado para isolar as dependências):

**No Linux/macOS:**
```bash
python -m venv venv
source venv/bin/activate
```

**No Windows:**
```cmd
python -m venv venv
venv\Scripts\activate
```

### 3. Instalação das Dependências

Com o ambiente virtual ativado, instale as bibliotecas necessárias contidas no `requirements.txt`:

```bash
pip install -r requirements.txt
```

### 4. Configuração do Banco de Dados da Aplicação

Inicie e crie as tabelas do banco de dados (SQLite) pela primeira vez:

```bash
flask db upgrade
# Se houver script de inserção inicial de dados:
# python init_db.py
```

### 5. Configuração do Serviço WAHA (WhatsApp API)

A aplicação utiliza o serviço WAHA para estabelecer sessão e viabilizar envios remotos no WhatsApp. Toda a persistência das sessões do WhatsApp e filas ficam no Docker.

Na raiz do projeto (onde está o arquivo `docker-compose.yml`), execute:

```bash
docker-compose up -d
```

Isso fará o download das imagens necessárias (WAHA, Postgres 15 e Redis) e deixará o serviço da API rodando localmente na porta `3000` (`http://localhost:3000`).

### 6. Executando o Servidor Web

Com o banco de dados configurado e o WAHA executando no Docker, suba a aplicação Flask:

```bash
python run.py
```

O servidor informará a porta na qual está rodando. Acesse a aplicação no navegador em:
**http://localhost:5000** ou **http://127.0.0.1:5000**

---

## ⚙️ Configurações Pós-Instalação (Admin)

Para que o envio de mensagens e a IA funcionem de forma integrada:
1. Acesse o sistema e navegue até as **Configurações Administrativas (`/admin`)**.
2. **Configuração da Instância WAHA:** Ajuste a URL do WhatsApp para a sua instância configurada (geralmente `http://localhost:3000`), e garanta que o nome de Sessão a ser utilizado bata com o que você ativará no WAHA.
3. **Integração IA:** Adicione a chave de API do **Google Gemini** para liberar as funções de refino de mensagens e templates.

> Para mais detalhes sobre as decisões arquiteturais, modelos do banco e estrutura de arquivos, consulte o [DOCUMENTACAO.md](DOCUMENTACAO.md) que se encontra na raiz do projeto.
