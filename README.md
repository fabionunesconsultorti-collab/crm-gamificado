# CRM Pro (Gamificado) 🚀

Sistema web completo, modular e de alta performance para **Gerenciamento Inteligente de Clientes (CRM)**, **Funil de Vendas Interativo (Kanban)**, **Prospecção Ativa**, **Atendimento Autônomo via WhatsApp com IA**, **Engine RAG Híbrido com Aprendizado Contínuo**, **Integração ERP Bling** e **Gamificação de Equipes Comerciais (XP e Níveis)**.

---

## 🌟 Principais Funcionalidades

### 1. 💼 Gestão de Clientes & Gamificação Comercial
- **Cadastro Completo & Lead Scoring**: Gestão de clientes e prospects com suporte a CPF/CNPJ, validação cadastral, categorias, Instagram e Website.
- **Sistema de Gamificação**: Rastreamento de pontos de fidelidade (XP), níveis hierárquicos (*Bronze, Prata, Ouro, VIP*) e badges para incentivar equipes comerciais.
- **Funil de Vendas (Kanban)**: Quadro interativo com suporte a *drag-and-drop*, métricas financeiras por etapa, cards proporcionais e conversão rápida de oportunidades.
- **Segmentação e Histórico**: Linha do tempo de compras, interações e conformidade com LGPD (*opt-in* auditável).
- **Importação e Exportação Massiva**: Suporte a importação via planilhas CSV/Excel com de-para dinâmico de colunas.

### 2. 📍 Prospecção Ativa (Google Maps Scraper)
- **Captação Automatizada de Leads**: Busca de empresas locais por nicho e região geográfica diretamente no Google Maps.
- **Enriquecimento de Dados**: Extração automática de telefones, endereços, websites, redes sociais e notas de avaliação.
- **Conversão em 1 Clique**: Ingestão direta dos leads minerados para o Funil de Vendas ou listas de disparo.

### 3. 🤖 Atendimento Autônomo & Mensageria WhatsApp (WAHA)
- **Gateway WAHA Integrado**: Executado em container Docker com persistência em PostgreSQL e filas Redis.
- **Captura Ativa & Webhooks**: Monitoramento de conversas em tempo real com captura de novas mensagens.
- **Debounce Inteligente de Mensagens**: Buffer em Redis/memória para agrupar áudios e mensagens sequenciais do cliente antes do processamento pela IA.
- **Qualificação Cadastral Progressiva**: O bot conduz o atendimento inicial, coletando dados (nome, necessidade, e-mail) e enriquecendo a ficha do lead no CRM.
- **Sistema Anti-Ban & Anti-Spam**: Intervalos randômicos humanizados, teto de disparos por hora, bloqueio fora do horário comercial e rotação de templates.
- **Normalização e Validação**: Tratamento automático de telefones com DDI, DDD e 9º dígito.
- **Templates Dinâmicos & Variáveis**: Mensagens personalizáveis com variáveis como `[NOME]`, `[VENDEDOR]`, `[DATA]`, `[HORA]` e logs de auditoria (`MessageLog`).

### 4. 🧠 Inteligência Artificial & RAG Avançado
- **Suporte Multi-Provedor**: Conexão com LLMs locais via **Ollama** (*DeepSeek R1, Llama 3, Mistral*) ou provedores em nuvem (**Google Gemini**, OpenAI) com salvaguardas anti-recusa.
- **Painel RAG (`/admin/rag`)**:
  - **Busca Híbrida**: Fusão entre busca vetorial densa (*Dense Embeddings*) e busca léxica (*BM25*).
  - **Calibração Dinâmica**: Ajuste em tempo real de pesos alfa/beta, limiares de confiança (*confidence threshold*) e telemetria.
- **Aprendizado Contínuo com Conversas**: Mineração automática dos diálogos do WhatsApp para detecção de dúvidas frequentes (FAQ) e alimentação da base de conhecimento.
- **Ingestão Semântica de Websites**: Crawler integrado para extrair e vetorizar automaticamente conteúdos de websites e páginas institucionais.
- **Motor Neural TensorFlow Local (`/admin/tensorflow`)**: Módulo neural embutido para classificação comportamental e predição de propensão de fechamento de leads.

### 5. 🔌 Central de Integrações & Módulo ERP Bling
- **Arquitetura Desacoplada**: Gerenciamento centralizado via `BaseIntegrationAdapter` e `IntegrationManager` (`/integrations/admin`).
- **Integração ERP Bling (API v3)**:
  - **Sincronização Bi-direcional**: Puxar e subir contatos com deduplicação inteligente por CPF/CNPJ, telefone e e-mail.
  - **Webhooks em Tempo Real**: Atualização instantânea de estoques, produtos, clientes e pedidos de venda.
- **Bling Analytics (`/integrations/bling/dashboard`)**:
  - Indicadores em tempo real: Faturamento, Ticket Médio e Total de Pedidos.
  - Gráficos interativos com a **Curva ABC Top 10** e status dos pedidos.
- **Relatórios Estratégicos (`/integrations/bling/reports`)**:
  - 📦 **Estoque Parado**: Capital travado por marca, fornecedor, categoria e faixas de tempo sem venda (30d, 60d, 90d+).
  - 👥 **Análise de Clientes (RFM)**: Classificação automática em clientes VIP, Recentes e Risco de Churn.
  - 📏 **Filtro por Tamanho & Tipo**: Análise de estoque e giro para confecção/varejo.
  - 📊 **Exportação CSV**: Download com filtros aplicados.

### 6. 🧩 Arquitetura Modular em 5 Setores & Plugins Desligáveis
O sistema é estruturado em 5 grandes setores funcionais, permitindo ativação ou desativação de módulos sem quebras:
1. **Gestão de Clientes (`gestao_clientes`)**: Funil Kanban, Cadastro, Lead Scoring, Prospecção e Gamificação.
2. **IA & Automação (`ia_automacao`)**: Provedores LLM, Engine RAG, TensorFlow Neural, Auto-Responder e FAQ Miner.
3. **Configuração (`configuracao`)**: Parâmetros do sistema, Anti-Ban, Backups e Auditoria.
4. **Integrações (`integracoes`)**: WAHA, Bling ERP e Webhooks.
5. **Plugins (`motor_plugins`)**: Extensões plug-and-play via `EventBus` e `PluginRegistry`.

- **Controle por Feature Flags (`/admin/modules`)**: Ligue e desligue recursos a quente com feedback visual imediato.
- **Sistema de Plugins (`/admin/plugins`)**: Cada nova funcionalidade pode ser encapsulada em `app/plugins/<nome_plugin>/` com manifesto `plugin.json` e isolamento total.
- **Gestão Granular de Permissões**: Grupos de acesso e autorizações por perfil (`/admin/groups`, `/admin/permissions`).

### 7. 🎨 Interface Moderna & Design System Glassmorphism
- **Design Glassmorphism**: Interface responsiva, refinada e desenvolvida com CSS nativo e moderno.
- **Suíte de Temas Dinâmicos**: Seletor instantâneo de temas com suporte a *Modern Dark*, *Cyberpunk/Neon*, *Emerald*, *Sunset*, *Sapphire* e mais.
- **Central de Backup**: Rotinas de exportação de dados com suporte a armazenamento local e sincronização com **Google Drive**.

---

## 🛠 Stack Tecnológico

| Camada | Tecnologias Utilizadas |
| :--- | :--- |
| **Backend Core** | Python 3.12, Flask (Padrão Blueprints MVC), Flask-SQLAlchemy, Flask-Migrate (Alembic) |
| **Bancos de Dados** | PostgreSQL 15 (Produção / Docker / Coolify) ou SQLite (Desenvolvimento) |
| **Mensageria & Filas** | WAHA API (WhatsApp HTTP API), Redis, RQ (Redis Queue), Threading |
| **Inteligência Artificial** | Ollama (Local: DeepSeek, Llama 3), Google Generative AI (Gemini), TensorFlow / Keras, BM25, Vector Embeddings |
| **Frontend** | HTML5 Semântico, Vanilla JavaScript, CSS3 Glassmorphism customizado (zero frameworks pesados) |
| **Infraestrutura & DevOps**| Docker, Docker Compose, Nginx, Coolify, Bash Scripts |

---

## 🏗 Estrutura do Projeto

```text
├── app/
│   ├── core/                  # Núcleo da arquitetura (ModuleRegistry, Plugins, EventBus)
│   ├── sectors/               # Setores de negócio da aplicação
│   ├── integrations/          # Adaptadores desacoplados de integração (Bling, etc.)
│   ├── plugins/               # Extensões plug-and-play isoladas
│   ├── admin/                 # Rotas e controles administrativos
│   ├── api/                   # Endpoints REST para consumo e webhooks
│   ├── auth/                  # Autenticação, sessões e permissões
│   ├── crm/                   # Clientes, Funil Kanban, Prospecção e Importações
│   ├── main/                  # Dashboard principal e métricas
│   ├── static/                # CSS (style.css, themes.css), JS e ícones
│   ├── tasks/                 # Workers assíncronos e tarefas em segundo plano (WhatsApp)
│   ├── templates/             # Visualizações Jinja estruturadas por módulo
│   ├── utils/                 # Handlers de IA, RAG, TensorFlow, WAHA e mensageria
│   ├── models.py              # Esquemas de banco de dados SQLAlchemy
│   └── __init__.py            # Application Factory
├── tests/                     # Suíte de testes unitários e de integração
├── docker-compose.yml         # Orquestração dos serviços WAHA, Postgres e Redis
├── start.sh / stop.sh         # Scripts de inicialização e desligamento automatizado
├── init_db.py                 # Criação e inicialização do banco de dados e usuário Admin
├── requirements.txt           # Dependências Python do projeto
├── DOCUMENTACAO.md            # Documentação técnica e arquitetural completa
└── GUIA_INTEGRACOES_BLING.md  # Manual passo a passo para configuração do ERP Bling
```

---

## 💻 Como Executar o Projeto

### ⚡ Inicialização Rápida (Linux / macOS)

O script orquestrador prepara o ambiente, inicializa os containers Docker e roda o servidor Flask:

```bash
./start.sh
```

Para encerrar os serviços com segurança:
```bash
./stop.sh
```

---

### 📦 Instalação Passo a Passo

#### 1. Pré-requisitos
- **Python 3.12+**
- **Git**
- **Docker** e **Docker Compose**

#### 2. Clonar o Repositório e Criar Ambiente Virtual

```bash
git clone https://github.com/fabionunesconsultorti-collab/crm-gamificado.git
cd crm-gamificado

# Criação do ambiente virtual
python -m venv venv

# Ativação do ambiente virtual
# No Linux/macOS:
source venv/bin/activate
# No Windows:
venv\Scripts\activate
```

#### 3. Instalar as Dependências

```bash
pip install -r requirements.txt
```

#### 4. Subir os Serviços de Infraestrutura (Docker)

Inicie o container do WAHA, PostgreSQL e Redis:

```bash
docker-compose up -d
```

O WAHA estará acessível em `http://localhost:3000` (painel em `/dashboard` com usuário `admin` e senha `admin123`).

#### 5. Configurar Variáveis de Ambiente (`.env`)

Crie ou edite o arquivo `.env` na raiz do projeto com as chaves necessárias:

```ini
# Configurações do Flask
SECRET_KEY=sua_chave_secreta_super_segura
FLASK_ENV=development

# Banco de Dados (PostgreSQL Docker ou SQLite local)
DATABASE_URL=postgresql://waha_user:waha_password@localhost:5432/waha
# Para SQLite em desenvolvimento leve, use:
# DATABASE_URL=sqlite:///crm.db

# WhatsApp (WAHA)
WAHA_API_URL=http://localhost:3000
WAHA_API_KEY=admin123
WAHA_SESSION=default

# Inteligência Artificial
AI_PROVIDER=gemini        # 'gemini' ou 'ollama'
GEMINI_API_KEY=sua_chave_da_google_ia
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=deepseek-r1:latest

# ERP Bling (Opcional - pode ser configurado via painel /integrations/admin)
BLING_CLIENT_ID=seu_client_id
BLING_CLIENT_SECRET=seu_client_secret
BLING_ACCESS_TOKEN=seu_access_token
```

#### 6. Inicializar o Banco de Dados

Crie as tabelas e o usuário administrador padrão (`admin` / `admin123`):

```bash
python init_db.py
```

#### 7. Executar a Aplicação Flask

```bash
python run.py
```

Acesse a aplicação no navegador em: **`http://localhost:5000`**

---

## 🧪 Executando os Testes

Para rodar a suíte de testes de integração e componentes:

```bash
venv/bin/python -m unittest discover -s tests
```

---

## ⚙️ Principais URLs do Sistema

| Rota | Descrição |
| :--- | :--- |
| `/` | Dashboard inicial com métricas de desempenho e ranking gamificado |
| `/crm` | Gestão de clientes com filtros inteligentes e buscas |
| `/crm/kanban` | Funil de vendas interativo (*drag-and-drop*) |
| `/crm/prospecting` | Painel de prospecção ativa via Google Maps |
| `/integrations/admin` | Central de integrações externas (Bling ERP e outras) |
| `/integrations/bling/dashboard` | Painel analítico de faturamento, vendas e curva ABC Bling |
| `/integrations/bling/reports` | Relatórios estratégicos de estoque parado e clientes RFM |
| `/admin` | Configurações gerais, instâncias WAHA e templates |
| `/admin/rag` | Painel de controle, calibração dinâmica e telemetria RAG |
| `/admin/modules` | Gerenciador modular de Feature Flags (*ligar/desligar funções*) |
| `/admin/plugins` | Central de plugins externos e extensões |
| `/admin/tensorflow` | Monitoramento e métricas do motor neural TensorFlow |
| `/admin/groups` | Controle de grupos e permissões granulares de usuários |

---

## 📖 Documentações Complementares

- [DOCUMENTACAO.md](DOCUMENTACAO.md) — Documentação técnica aprofundada, diagramas de arquitetura, fluxo de dados e guia de implantação em produção (Coolify / Docker).
- [GUIA_INTEGRACOES_BLING.md](GUIA_INTEGRACOES_BLING.md) — Manual passo a passo para configuração de credenciais, permissões de escopo e webhooks no Bling ERP v3.

---

## 📄 Licença e Autoria

Desenvolvido para gestão comercial estratégica, prospecção e relacionamento automatizado com clientes.
