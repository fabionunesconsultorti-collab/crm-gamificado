# Documentação Estrutural - CRM Pro

Bem-vindo à documentação técnica do **CRM Pro**. Este arquivo visa explicar de forma humana e acessível o escopo atual, a arquitetura e as decisões técnicas deste software, servindo como mapa para futuros aprimoramentos.

---

## 1. Visão Geral
O **CRM Pro** é um sistema web responsivo desenhado para gerenciamento inteligente de clientes (CRM), gestão de funil de vendas (Kanban) e automação de mensageria com foco na integração via WhatsApp. O sistema inclui rastreamento de fidelidade (XP e Níveis) que engaja equipes comerciais e aprimora a visão da jornada do cliente.

A arquitetura escolhida minimiza a dependência de serviços externos complexos sempre que possível, centralizando regras de negócio no próprio motor nativo.

## 2. Tecnologias e Ferramentas (Stack Tecnológico)
- **Backend Core**: `Python 3.12`
- **Framework Web**: `Flask` (Padrão de arquitetura MVC: *Models, Views, Controllers* convertidos para Blueprints).
- **Banco de Dados**: `SQLite` através do ORM `SQLAlchemy`. Foi escolhido para facilitar a distribuição e os backups iniciais sem configuração de cluster.
- **Migrações e Modelagem**: `Flask-Migrate` (`Alembic`) para gerenciar as mudanças no banco de dados com comandos simples de terminal.
- **Frontend / Interface Visual**: HTML5, Vanilla JS e Sistema Customizado de CSS focado em "Glassmorphism" — usando arquivos estáticos locais ao invés de grandes bibliotecas terceiras como Tailwind ou Bootstrap, para que tenhamos máximo controle e desempenho limpo, gerando o arquivo `/static/css/style.css`.
- **Comunicação Web API (Requisições HTTP)**: A biblioteca `requests` do Python possibilita o despache instantâneo de mensagens pelo servidor diretamente para a API WhatsApp (WAHA).

## 3. Estrutura de Diretórios e Blueprints
A aplicação usa a estrutura em **Blueprints** para facilitar a escalabilidade de módulos separados:

- `app/` *(Centro Espinhal)*
  - `__init__.py`: (Fábrica da Aplicação) Inicializa o app, junta as extensões do Flask e configura URL e chaves secretas.
  - `models.py`: Toda a estrutura (schemas) das tabelas que vão pro banco de dados (Usuários, Clientes, Lojas, Configurações e Histórico de Logs). 
  - `main/`: Módulo e rotas para Landing Page / Dashboard, incluindo o modelo da Tela de Ranking.
  - `auth/`: Módulo independente gerindo Autenticações (login, logout, session data e senhas seguras por hash).
  - `admin/`: Módulo e telas administrativas, acessíveis apenas para *admin/gerentes*. Focado em adicionar/remover Lojas, visualizar todos os Logs, inserir templates novos e administrar permissionamento e configuração das instâncias WAHA (WhatsApp).
  - `crm/`: Coração de Vendas. Concentra o motor visual do CRUD de Clientes, a visualização dinâmica do Kanban (*drag-n-drop*) e a funcionalidade de Importação Massiva de CSV.
  - `api/`: O roteador silencioso e moderno. Mantém endpoints focados e padronizados no padrão `REST (/api/*)` prontos para servirem Webhooks externos (ouvidoria), ou para envio massivo programado que independe do navegador do cliente.
  - `utils/`: Contém arquivos vitais como `messaging.py` (Engine para processar as variáveis como nome/data das mensagens) e a classe `WahaAPI` (Empacotador abstrato para as chamadas de rede do Whatsapp).
- `run.py`: O ignitor. O local onde você dá a partida no servidor web para testes em desenvolvimento ou na porta principal da sua aplicação.

## 4. API, Webhooks e Módulo de Mensageria (WAHA API)
Na evolução do CRM incorporamos o Módulo Focado em Disparos e Centralização de Mensagens de WhatsApp via **WAHA (WhatsApp HTTP API)**. Em vez de usar ferramentas externas engessadas, a fundação está incorporada ao próprio CRM:

1. **Gestão de Templates Dinâmicos (`/admin/templates`)**: Banco de matrizes de frases. Por exemplo: *"Olá, [NOME]"* pode ser parametrizado para os operadores não precisarem ficar colando textos variados.
2. **Motor de Interpolação Textual (`utils.messaging`)**: Usa Expressões Regulares (`RegEx`) para converter as variáveis lógicas do template nos dados exatos da tabela e contexto do remetente a partir da tabela SQL.
   - Variáveis suportadas localmente: `[NOME], [NOME_COMPLETO], [DATA], [HORA], [STATUS], [VENDEDOR]`.
3. **Tracking & Observabilidade (`MessageLog`)**: Um sistema que funciona silenciosamente no banco registrando o autor, se o cliente é validado com sucesso e se foi gerado API ou disparado um link puro (`wa.me`) via Browser.
4. **Acoplador de API (`utils/waha.py`)**: Arquivo Python que mapeia a documentação oficial da WAHA API. Ele gerencia e consulta em tempo real a URL do seu servidor (`waha_api_url`), Chave de API (`waha_api_key`) e a Sessão ativa (`waha_session_name` / `waha_instance`), persistidas no modelo `WahaInstance` do banco de dados (com suporte a fallback na tabela `Setting`).

## 5. Mapeamento Relevante das Variáveis do Banco de Dados
A tabela **Client** possui um escopo estendido para varejo moderno e prospecção ativa:
- **`public_id`** (UUIDv4): Criado para integração robusta com outros sistemas via API, para não expor a contagem de Identificação do Banco Central (Nº ID).
- **`cpf`**: Compatível com **CPF** (11 dígitos / `000.000.000-00`) e **CNPJ** (14 dígitos / `00.000.000/0001-00`). Atrelado a integridade única se informado (`VARCHAR(32)`).
- **`phone`**: Celular com verificação única, crucial para disparo unificado sem contatar a mesma pessoa com ruídos idênticos.
- **`segment` / `category`**: Segmento de mercado / nicho de atuação do contato (ex: *Panificadora, Academia, Restaurante*), preenchido automaticamente pela **Prospecção Ativa (Google Maps)** ou informado manualmente no cadastro.
- **`instagram`**: Perfil ou URL de Instagram do contato (ex: `@empresa` ou link completo).
- **`website`**: Site / domínio oficial da empresa prospectada.
- **Parâmetros Estratégicos**: `tier` (nível: bronze, prata, ouro, vip), `loyalty_points` (pontuação baseada na frequência e engajamento), `badges` (tags de segmentação CSV customizáveis) e LGPD (`opt_in`, permitindo auditoria local para envio em conformidade com as regras brasileiras).

---

## 6. Configuração e Credenciais do WAHA (WhatsApp API)
O serviço WAHA (WhatsApp HTTP API) roda encapsulado via Docker junto com PostgreSQL e Redis para garantir persistência de sessões e filas assíncronas.

### Arquitetura do Docker Compose
No arquivo `docker-compose.yml` da raiz:
```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15
    restart: always
    environment:
      POSTGRES_DB: waha
      POSTGRES_USER: waha_user
      POSTGRES_PASSWORD: waha_password
    volumes:
      - ./postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:alpine
    restart: always
    volumes:
      - ./redis_data:/data

  waha:
    image: devlikeapro/waha
    restart: always
    ports:
      - "3000:3000"
    environment:
      - WHATSAPP_API_DATABASE_URL=postgresql://waha_user:waha_password@postgres:5432/waha
      - WHATSAPP_API_REDIS_URL=redis://redis:6379
      - WHATSAPP_API_SESSION_STORAGE=postgres
      - WHATSAPP_API_HOSTNAME=0.0.0.0
      - TZ=America/Sao_Paulo
      # Credenciais Fixas para Dashboard e API
      - WAHA_DASHBOARD_ENABLED=True
      - WAHA_DASHBOARD_USERNAME=admin
      - WAHA_DASHBOARD_PASSWORD=admin123
      - WHATSAPP_SWAGGER_USERNAME=admin
      - WHATSAPP_SWAGGER_PASSWORD=admin123
      - WAHA_API_KEY=admin123
    depends_on:
      - postgres
      - redis
```

### Credenciais Padrão do WAHA
- **Dashboard / Swagger:** `http://localhost:3000/dashboard`
- **Usuário:** `admin`
- **Senha:** `admin123`
- **Chave de API (`X-Api-Key`):** `admin123`

---

## 7. Manual Detalhado: Como Rodar a Aplicação Localmente

### Método 1: Inicialização Automatizada (Recomendado)
O projeto conta com scripts orquestradores que realizam todas as checagens e inicializações automaticamente:

```bash
# 1. Torne os scripts executáveis (apenas na primeira vez)
chmod +x start.sh stop.sh

# 2. Inicie todo o ecossistema (Docker + Banco + Flask)
./start.sh
```

**O que o `start.sh` executa:**
1. Valida se o Docker está instalado e com o daemon ativo.
2. Sobe os containers (Postgres, Redis, WAHA) via `docker compose up -d`.
3. Executa um *healthcheck* aguardando a porta `3000` do WAHA responder.
4. Detecta ou cria o ambiente virtual Python (`venv`).
5. Valida e instala dependências do `requirements.txt`.
6. Executa `init_db.py` para criar tabelas e garantir o usuário `admin` padrão.
7. Dispara o servidor Flask em `http://localhost:5000`.
8. Ao receber `Ctrl+C`, oferece opção para pausar os containers automaticamente.

Para pausar os serviços do Docker posteriormente:
```bash
./stop.sh
```

---

### Método 2: Inicialização Manual Passo a Passo
Caso deseje rodar cada componente manualmente:

1. **Subir os serviços Docker:**
   ```bash
   docker compose up -d
   ```
2. **Ativar o ambiente virtual Python:**
   ```bash
   # Linux / macOS:
   python3 -m venv venv
   source venv/bin/activate

   # Windows:
   python -m venv venv
   venv\Scripts\activate
   ```
3. **Instalar dependências:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Criar tabelas e administrador padrão:**
   ```bash
   python init_db.py
   ```
5. **Iniciar a aplicação Flask:**
   ```bash
   python run.py
   ```

### Acessos Locais:
- **CRM Web:** [http://localhost:5000](http://localhost:5000) (Login: `admin` / Senha: `admin123`)
- **Painel WAHA:** [http://localhost:3000/dashboard](http://localhost:3000/dashboard) (Login: `admin` / Senha: `admin123`)

---

## 8. Manual de Portabilidade: Como Portar e Fazer Deploy em Servidores (VPS / Produção)

Este guia cobre o passo a passo completo para migrar a aplicação para um servidor Linux (Ubuntu 22.04 / 24.04 LTS) em provedores como Hetzner, DigitalOcean, AWS, Oracle Cloud ou VPS dedicado.

### 8.1. Requisitos Mínimos do Servidor
- **SO:** Ubuntu 22.04 LTS ou superior.
- **CPU:** Mínimo de 2 vCPUs (o Chromium do WAHA exige capacidade de processamento para renderizar webhooks de mensagens).
- **Memória RAM:** 4 GB recomendados (mínimo 2 GB com Swap configurada).
- **Disco:** 20 GB SSD ou superior.
- **Domínio ou Subdomínio:** Apontado para o IP público do servidor (ex: `crm.seudominio.com.br` e `waha.seudominio.com.br`).

---

### 8.2. Passo 1: Preparação do Sistema Operacional
Acesse o servidor via SSH e atualize os pacotes:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl git ufw python3 python3-pip python3-venv nginx certbot python3-certbot-nginx
```

Instale o **Docker** e o **Docker Compose plugin**:
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
docker --version
docker compose version
```

---

### 8.3. Passo 2: Clonar o Projeto no Servidor
Recomenda-se colocar o projeto em `/var/www/crm` ou no diretório home:

```bash
sudo mkdir -p /var/www/crm
sudo chown -R $USER:$USER /var/www/crm
cd /var/www/crm

# Clone o repositório
git clone <URL_DO_SEU_REPOSITORIO> .
```

---

### 8.4. Passo 3: Configurar Variáveis de Ambiente e Segurança
Em produção, não use chaves padrão. Crie um arquivo `.env` na raiz do projeto:

```bash
cat << 'EOF' > .env
SECRET_KEY=gere_uma_chave_longa_e_aleatoria_aqui
DATABASE_URL=sqlite:////var/www/crm/crm.db
WAHA_DASHBOARD_USERNAME=admin
WAHA_DASHBOARD_PASSWORD=sua_senha_forte_waha
WAHA_API_KEY=sua_chave_secreta_api_waha
EOF
```

> **Dica para gerar `SECRET_KEY` aleatória:**
> ```bash
> python3 -c "import secrets; print(secrets.token_hex(32))"
> ```

---

### 8.5. Passo 4: Subir a Stack de Mensageria (Docker)
Inicie os containers do PostgreSQL, Redis e WAHA:

```bash
docker compose up -d
```

Verifique se estão operando normalmente:
```bash
docker compose ps
docker logs crm-waha-1 --tail 30
```

---

### 8.6. Passo 5: Configurar o Python e Gunicorn (Servidor de Aplicação)
Em servidores de produção, o servidor embutido do Flask (`app.run`) não deve ser utilizado. Utiliza-se o **Gunicorn** como servidor WSGI de alto desempenho.

1. **Crie e ative o ambiente virtual:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. **Instale as dependências e o Gunicorn:**
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   pip install gunicorn
   ```

3. **Inicialize o Banco de Dados:**
   ```bash
   python init_db.py
   ```

---

### 8.7. Passo 6: Configurar o Systemd (Daemon com Auto-Restart)
Para que o CRM inicialize automaticamente com o servidor e reinicie caso caia, crie um serviço no `systemd`:

```bash
sudo nano /etc/systemd/system/crm.service
```

Insira a seguinte configuração (ajuste o usuário e caminhos se necessário):
```ini
[Unit]
Description=CRM Pro - Servidor Flask via Gunicorn
After=network.target docker.service
Requires=docker.service

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/var/www/crm
Environment="PATH=/var/www/crm/venv/bin"
ExecStart=/var/www/crm/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:5000 run:app --timeout 120

Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Ative e inicie o serviço:
```bash
sudo systemctl daemon-reload
sudo systemctl enable crm
sudo systemctl start crm
sudo systemctl status crm
```

---

### 8.8. Passo 7: Configurar Nginx como Reverse Proxy e SSL Gratuito (HTTPS)

Crie um arquivo de configuração para o site no Nginx:
```bash
sudo nano /etc/nginx/sites-available/crm
```

Conteúdo recomendado:
```nginx
server {
    listen 80;
    server_name crm.seudominio.com.br;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# (Opcional) Proxy para o painel WAHA com subdomínio próprio
server {
    listen 80;
    server_name waha.seudominio.com.br;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Suporte a WebSocket (essencial para o WAHA QR Code dinâmico)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Ative o site e teste a sintaxe:
```bash
sudo ln -s /etc/nginx/sites-available/crm /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

Gere certificados SSL gratuitos com o **Certbot**:
```bash
sudo certbot --nginx -d crm.seudominio.com.br -d waha.seudominio.com.br
```

O Certbot renovará os certificados automaticamente a cada 90 dias.

---

### 8.9. Passo 8: Firewall (UFW) e Segurança de Rede
Proteja o servidor mantendo fechadas as portas internas (3000, 5000, 5432, 6379), deixando públicas apenas as portas web e SSH:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

---

### 8.10. Passo 9: Rotina de Backup Recomendada
Para garantir a segurança dos dados dos clientes e sessões:

1. **Banco SQLite:** O arquivo `crm.db` contém todos os dados do CRM. Faça cópias periódicas via cron:
   ```bash
   cp /var/www/crm/crm.db /var/backups/crm_$(date +%F).db
   ```
2. **Dados do Docker:** As pastas `./postgres_data`, `./redis_data` e `./waha_data` armazenam as sessões conectadas do WhatsApp. Inclua-as em seus snapshots de disco ou rotinas de backup comprimidas (`tar.gz`).

---

## 9. Manual de Hospedagem no Coolify (PaaS Auto-Hospedado)

O **Coolify** é uma plataforma open-source (alternativa ao Heroku, Railway e Render) que gerencia containers Docker, deploys automáticos via Git e certificados SSL gratuitos com renovação automática via Traefik.

O projeto já conta com o arquivo [Dockerfile](Dockerfile) e a stack orquestrada [docker-compose.coolify.yml](docker-compose.coolify.yml) prontos para rodar no Coolify.

---

### 9.1. Como Funciona a Arquitetura no Coolify
No Coolify, todos os 4 serviços rodam na mesma rede interna do Docker:
- **`crm` (Porta 5000):** Aplicação Flask servida via Gunicorn.
- **`waha` (Porta 3000):** API do WhatsApp com persistência de sessões.
- **`postgres` (Porta 5432):** Banco de dados relacional interno do WAHA.
- **`redis` (Porta 6379):** Fila assíncrona e cache do WAHA.

> 🌟 **Grande Vantagem no Coolify:** O CRM se comunica com o WhatsApp de forma **100% interna** pela rede Docker através do endereço `http://waha:3000`, sem precisar expor a porta da API publicamente ou gastar tráfego externo!

---

### 9.2. Passo a Passo de Deploy no Coolify

#### Passo 1: Subir o Projeto no GitHub ou GitLab
Certifique-se de que as alterações e os novos arquivos (`Dockerfile`, `.dockerignore`, `docker-compose.coolify.yml`) foram comitados e enviados para o seu repositório Git:
```bash
git add Dockerfile .dockerignore docker-compose.coolify.yml requirements.txt
git commit -m "feat: suporte a deploy no Coolify via Docker Compose"
git push origin main
```

#### Passo 2: Criar o Recurso no Coolify
1. Acesse o painel web do seu servidor **Coolify**.
2. Vá em **Projects** e selecione o seu projeto/ambiente (ex: `Production`).
3. Clique no botão **+ New Resource**.
4. Selecione **Git Repository (ou Docker Compose)**:
   - Se escolher **Private/Public Repository**: Conecte seu repositório Git.
   - Na opção de **Build Pack**, selecione **Docker Compose**.
   - Em **Docker Compose Location**, informe: `/docker-compose.coolify.yml`.

#### Passo 3: Configurar os Domínios e SSL
No painel do serviço criado no Coolify:
1. Localize a aba de **Domains / FQDN**:
   - **Para o CRM:** Defina o domínio principal: `https://crm.seudominio.com.br` (apontando para a porta `5000` do serviço `crm`).
   - *(Opcional)* **Para o WAHA Dashboard:** Se quiser acessar o painel de QR Code do WhatsApp remotamente por um subdomínio, configure: `https://waha.seudominio.com.br` (apontando para a porta `3000` do serviço `waha`).
2. O Coolify (via Traefik) gerará e configurará os certificados SSL **HTTPS (Let's Encrypt)** automaticamente.

#### Passo 4: Configurar as Variáveis de Ambiente
Na aba **Environment Variables** do Coolify, adicione:

| Variável | Descrição | Exemplo de Valor |
|---|---|---|
| `SECRET_KEY` | Chave criptográfica do Flask | `gerar_uma_chave_longa_hex_aleatoria` |
| `POSTGRES_PASSWORD` | Senha interna do PostgreSQL | `waha_secret_pass_2026` |
| `WAHA_DASHBOARD_USERNAME` | Usuário do painel WAHA | `admin` |
| `WAHA_DASHBOARD_PASSWORD` | Senha do painel WAHA | `sua_senha_forte_aqui` |
| `WAHA_API_KEY` | Chave de autenticação da API | `sua_chave_api_secreta` |

#### Passo 5: Fazer o Deploy
1. Clique no botão **Deploy** no topo da tela do Coolify.
2. O Coolify irá:
   - Baixar as imagens do PostgreSQL, Redis e WAHA.
   - Construir a imagem Docker da sua aplicação CRM Flask.
   - Criar os volumes persistentes (`crm_data`, `postgres_data`, `redis_data`, `waha_data`).
   - Configurar o roteamento seguro com HTTPS.

---

### 9.3. Configurando a Integração WAHA no CRM após o Deploy
Assim que o deploy terminar:
1. Abra seu navegador em `https://crm.seudominio.com.br`.
2. Faça login com o usuário administrador padrão (`admin` / `admin123`).
3. Vá em **Admin (`/admin`)** -> **Instâncias WAHA**.
4. Configure a instância com os seguintes dados:
   - **Nome:** Instância Produção
   - **URL da API:** `http://waha:3000` *(o nome do serviço na rede interna do Coolify)*
   - **API Key:** O mesmo valor que você configurou na variável `WAHA_API_KEY`.
   - **Sessão:** `default`
5. Clique em salvar e sincronizar o QR Code para conectar o WhatsApp da sua empresa!

---

## 10. Inteligência Artificial com Ollama (Docker Local)

O **CRM Pro** conta com suporte nativo ao **Ollama**, rodando diretamente em container Docker na porta `11434`.

### 10.1. Principais Vantagens do Ollama Local
- **100% Gratuito & Ilimitado:** Não há cobrança por token ou limite mensal como em APIs de terceiros.
- **Privacidade Total:** Os dados e conversas de seus clientes não saem do seu servidor VPS/Local.
- **Resiliente & Offline:** Não depende de estabilidade de conexões externas com OpenAI ou Google.

### 10.2. Funcionalidades da IA no Sistema
1. **Reescrita de Mensagens (Anti-Spam Humanizado):** Durante o disparo em massa no CRM, cada mensagem gerada para o cliente é sutilmente reescrita mantendo o sentido original e preservando as variáveis mágicas (`[NOME]`, `[DATA]`, `[STATUS]`, `[VENDEDOR]`).
2. **Respostas Automáticas no WhatsApp:** Responde clientes de maneira atenciosa e comercial através de webhooks.
3. **Criação de Novos Textos e Templates (`/admin/templates`):** Permite aos operadores ou gerentes digitar uma instrução (ex: *"Cobrança amigável com desconto para pagamento à vista hoje"*) e a IA gera a mensagem pronta e estruturada.

### 10.3. Como Baixar e Gerenciar Modelos no Docker

Para baixar e usar um modelo leve e rápido (ideal para CPU):

```bash
# Opção Recomendada: Meta Llama 3.2 (3B - rápido e preciso)
docker exec -it crm-ollama-1 ollama run llama3.2

# Opção Ultra-Leve: Meta Llama 3.2 1B (~1.3 GB, altíssima velocidade em CPUs modestas)
docker exec -it crm-ollama-1 ollama run llama3.2:1b

# Opção Raciocínio: DeepSeek R1 1.5B
docker exec -it crm-ollama-1 ollama run deepseek-r1:1.5b
```

Para listar os modelos atualmente instalados:
```bash
docker exec -it crm-ollama-1 ollama list
```

### 10.4. Configurações no Painel Admin (`/admin/settings` -> Aba IA)
- **Provedor:** Selecione `🦙 Ollama (Docker Local - 100% Gratuito & Ilimitado)`
- **URL do Ollama:** `http://localhost:11434` (ou `http://ollama:11434` no Coolify/Docker)
- **Modelo:** `llama3.2` (ou o nome do modelo que você baixou)
- **Clique no botão "Testar Conexão & Listar Modelos"** para verificar em tempo real o status do container.

---

## 11. Sistema Anti-Ban / Anti-Spam e Proteção de Disparos WhatsApp (WAHA)

O **CRM Pro** conta com um ecossistema nativo e completo de **Proteção Anti-Ban e Anti-Spam** projetado especificamente para mitigar os riscos de bloqueio ou banimento de chips no WhatsApp durante disparos individuais e campanhas em massa.

### 11.1. Por que a Proteção Anti-Spam é Fundamental?
O WhatsApp utiliza inteligência algorítmica e análise comportamental rigorosa para identificar automações abusivas. Os principais gatilhos de bloqueio são:
1. **Rajadas não-humanas:** Disparos de dezenas de mensagens no mesmo segundo sem nenhum intervalo.
2. **Textos idênticos em massa:** O mesmo hash de mensagem enviado para centenas de contatos sem personalização.
3. **Pico repentino em números novos:** Linhas recém-cadastradas no WhatsApp enviando centenas de mensagens no primeiro dia.
4. **Denúncias de usuários (Spam Report):** Mensagens recebidas em horários inoportunos (como madrugada ou noite) aumentam exponencialmente a taxa de bloqueios e denúncias diretas.

Para neutralizar esses fatores, o CRM Pro implementa uma **estratégia de defesa em 5 camadas**:

```mermaid
graph TD
    A[Disparo Iniciado] --> B{Horário de Silêncio?}
    B -- Sim --> C[Bloqueia Envio - Protege o Chip]
    B -- Não --> D{Cota Horária / Diária Atingida?}
    D -- Sim --> E[Pausa Envio com Alerta 429]
    D -- Não --> F[Calcula Delay Humanizado Aleatório]
    F --> G[Opcional: Reescrita com IA Ollama]
    G --> H[Envia via WAHA API]
    H --> I[Incrementa Contadores e Agenda Próximo]
```

---

### 11.2. As 5 Camadas de Proteção

#### 1. Delays Dinâmicos e Pausas Humanizadas (Random Jitter)
- Cada mensagem consecutiva aguarda um tempo randômico configurável entre `min_delay_seconds` e `max_delay_seconds` (ex: 5 a 15 segundos).
- Durante o disparo em massa na interface web (`/crm/bulk-message`), uma barra visual exibe uma contagem regressiva em tempo real: *"Aguardando 9s (anti-ban humanizado)..."*, simulando o comportamento de digitação de um ser humano.

#### 2. Rate Limiting e Cotas de Disparo (Por Hora e Por Dia)
- **Limite Horário (`max_messages_per_hour`):** Limite máximo seguro por hora (padrão sugerido: 60 a 80 msgs/hora).
- **Limite Diário (`max_messages_per_day`):** Teto máximo diário de mensagens por instância (padrão sugerido: 300 a 500 msgs/dia para números maduros).
- **Auto-Reset Inteligente:** Os contadores de hora e dia resetam automaticamente assim que o relógio vira a hora cheia ou a meia-noite, sem necessidade de rotinas cron externas complexas.

#### 3. Modo Aquecimento Gradual (Warm-up de Chips Novos)
Se o número do WhatsApp foi ativado recentemente, ativar o **Modo Aquecimento** calcula uma rampa progressiva automática baseada nos dias decorridos desde a data de início (`warmup_start_date`):
- **Dia 1:** Máximo de 20 mensagens/dia
- **Dia 2:** Máximo de 40 mensagens/dia
- **Dia 3:** Máximo de 70 mensagens/dia
- **Dia 4:** Máximo de 110 mensagens/dia
- **Dia 5:** Máximo de 160 mensagens/dia
- **Dia 6:** Máximo de 220 mensagens/dia
- **Dia 7 em diante:** Máximo de 300 mensagens/dia (ou o teto diário configurado)

#### 4. Horário de Silêncio (Quiet Hours)
- Bloqueia envios automáticos e disparos em massa em horários de repouso definidos (ex: das **22:00** às **08:00**).
- O algoritmo calcula com precisão inclusive faixas que atravessam a meia-noite.
- Evita que clientes recebam notificações tarde da noite e cliquem no botão "Denunciar como Spam" do WhatsApp.

#### 5. Variação Textual com IA Ollama Local (Anti-Spam Semântico)
- Integrado ao módulo de IA (`/admin/settings` e tela de envio em massa), o sistema pode reescrever ligeiramente cada texto de forma semântica preservando as variáveis mágicas (`[NOME]`, `[DATA]`, `[STATUS]`, `[VENDEDOR]`).
- Isso faz com que cada mensagem enviada tenha uma estrutura léxica ligeiramente diferente, quebrando o padrão de "mensagens clone".

---

### 11.3. Parâmetros do Banco de Dados (`WahaInstance`)

| Campo | Tipo | Descrição | Valor Padrão |
|---|---|---|---|
| `enable_anti_ban` | Boolean | Liga ou desliga as proteções nesta instância | `True` |
| `min_delay_seconds` | Integer | Intervalo mínimo aleatório entre mensagens (segundos) | `5` |
| `max_delay_seconds` | Integer | Intervalo máximo aleatório entre mensagens (segundos) | `15` |
| `max_messages_per_hour` | Integer | Limite máximo de mensagens enviadas por hora | `80` |
| `max_messages_per_day` | Integer | Limite nominal máximo de mensagens por dia | `500` |
| `quiet_hours_enabled` | Boolean | Ativa bloqueio de envios fora do horário comercial | `True` |
| `quiet_hours_start` | String | Hora de início do silêncio no formato HH:MM | `22:00` |
| `quiet_hours_end` | String | Hora de término do silêncio no formato HH:MM | `08:00` |
| `warmup_mode` | Boolean | Liga o algoritmo de escalonamento para chips novos | `False` |
| `warmup_start_date` | DateTime | Data do início do ciclo de aquecimento | *Data de ativação* |
| `hourly_count` | Integer | Mensagens disparadas na hora corrente | `0` |
| `daily_count` | Integer | Mensagens disparadas no dia corrente | `0` |
| `last_sent_at` | DateTime | Timestamp do último disparo realizado | `None` |

---

### 11.4. Como Configurar e Operar no Painel do CRM

#### 1. Configurar na Administração (`/admin/settings` -> Seção Instâncias WAHA)
1. Acesse o CRM como Administrador e navegue até **Configurações (`/admin/settings`)**.
2. No card de cada instância conectada, você verá as barras de progresso de **Cota Horária** e **Cota Diária** em tempo real.
3. Clique em **"🛡️ Configurar Anti-Ban"**:
   - Ative/Desative a proteção global daquela linha.
   - Ajuste os delays mínimo e máximo (recomendado: entre 5s e 20s).
   - Defina os limites por hora e por dia de acordo com a maturidade do seu chip.
   - Ative o Horário de Silêncio e configure as horas permitidas.
   - Para números novos, marque **"Modo Aquecimento (Warm-up)"**.
4. Se necessário, utilize o botão **"Zerar Contadores"** para reiniciar as contagens daquele dia/hora.

#### 2. Operação no Disparo em Massa (`/crm/bulk-message`)
- Ao selecionar a instância de envio, o sistema exibe dinamicamente o resumo de segurança e o delay configurado.
- Durante o processo, cada mensagem é processada individualmente:
  1. O CRM envia a mensagem para o contato atual.
  2. Atualiza a contagem da instância.
  3. Sorteia um tempo de descanso (ex: 8 segundos).
  4. Exibe a contagem regressiva na tela antes de seguir para o próximo contato.
- Se o limite de cota ou o horário de silêncio for atingido durante o disparo, o processo é pausado com segurança, preservando a lista de clientes para envio posterior.

#### 3. API Externa de Envio (`/crm/api/external/send`)
- Aplicações externas ou automações que chamem o endpoint de envio do CRM são protegidas pelas mesmas regras:
  - Se a instância estiver no horário de silêncio ou atingir o limite, a requisição retorna status **429 (Too Many Requests)** com mensagem descritiva do motivo do bloqueio.
  - A tentativa é registrada nos logs do sistema sem queimar a sessão do WhatsApp.

---

### 11.5. Testes Automatizados

O sistema inclui uma suíte completa de testes unitários para certificar a estabilidade do Anti-Ban:

```bash
# Executar a suíte de testes de Anti-Ban
./venv/bin/python3 -m unittest tests/test_antiban.py

# Ou rodar todos os testes do projeto
./venv/bin/python3 -m unittest discover tests
```

**Cenários testados automaticamente:**
- Curva de aquecimento progressiva dia a dia (`test_warmup_daily_limits`).
- Detecção de horários de silêncio com e sem travessia de meia-noite (`test_quiet_hours`).
- Reset automático de contadores na virada de hora e dia (`test_auto_reset_counters`).
- Bloqueio por estouro de cota horária e diária (`test_hourly_and_daily_limit_blocking`).
- Incremento correto ao enviar mensagem (`test_record_message_sent`).
- Endpoints REST de estatísticas (`/crm/api/waha/<id>/anti_ban_stats`) e reset (`/crm/api/waha/<id>/reset_counters`).

---

## 12. Prospecção Ativa de Leads (Google Maps Scraper)

O **CRM Pro** conta com um motor nativo de **Prospecção Ativa (Outbound Lead Generation)** integrado ao container Docker `gosom/google-maps-scraper` (porta `8080`).

### 12.1. Arquitetura do Módulo

1. **Interface do Usuário (`/crm/prospeccao`):**
   - Formulário para submissão de buscas geográficas (ex: *"Academias em Sumaré SP"* ou *"Clínicas odontológicas Campinas"*).
   - Seletor de profundidade de páginas (1 a 5).
   - Checkbox para extração de e-mails em websites comerciais.
   - Tabela de monitoramento em tempo real com polling automático via JavaScript Vanilla (atualiza badges, contadores de minerados e leads importados sem recarregar a tela).
   - Acesso direto com filtros aplicados ao **Funil Kanban** (`/crm/kanban?badge=job_<id>`) e à **Lista de Clientes** (`/crm/clients?badge=job_<id>`).

2. **Processamento Assíncrono (`app/tasks/lead_scraper.py`):**
   - Cria o registro de controle na tabela `ScrapingJob`.
   - Dispara a requisição REST para `http://localhost:8080/api/v1/jobs`.
   - Executa polling seguro até o container finalizar a extração.
   - Realiza download dos dados brutos e inicia a higienização.

3. **Higienização e Normalização E.164 (`normalize_brazilian_phone`):**
   - Limpa caracteres especiais, parênteses e hifens.
   - Trata DDDs válidos de todo o território brasileiro (11 a 99).
   - Adiciona o 9º dígito automaticamente para celulares antigos de 8 dígitos.
   - Diferencia celulares de telefones fixos comerciais (`is_mobile`).
   - Normaliza para o padrão E.164 brasileiro (`55 + DDD + 9 dígitos` para celulares, `55 + DDD + 8 dígitos` para fixos).

4. **Deduplicação e Conformidade LGPD:**
   - Consulta o banco antes de inserir para evitar violação de unicidade (`Client.phone`).
   - Verifica por número completo e sufixo de 8 dígitos.
   - Se o lead for novo, insere na tabela `Client` com:
     - `status = 'lead'` (primeira coluna do Funil Kanban).
     - `lead_source = 'Google Maps'`.
     - `opt_in = False` (marcado como outbound para conformidade com a LGPD).
     - `badges = 'outbound_gmaps,job_<id>'`.
     - `notes` preenchidas com dados ricos de contexto (categoria, nota de avaliação ⭐, contagem de reviews e website).

### 12.2. Recomendações Práticas Contra Bloqueios de IP (Google Maps)

O Google Maps aplica mecanismos de rate-limiting (CAPTCHAs e bloqueios temporários de IP) quando detecta volumes excessivos ou simultâneos de requisições:

1. **Controle de Concorrência:**
   - Mantenha a variável `CONCURRENCY=4` (padrão configurado no `docker-compose.yml`). Evite valores maiores que 8 em IPs residenciais ou VPS sem proxy.
2. **Profundidade Recomendada (Depth):**
   - Utilize **Profundidade 1 ou 2** (~20 a 40 empresas por busca). Essa profundidade é rápida (~40 a 60 segundos), possui baixíssimo risco de flag e traz os negócios mais relevantes e com melhores dados cadastrais.
3. **Intervalo Entre Buscas:**
   - Evite disparar múltiplas buscas seguidas simultaneamente no mesmo IP. Aguarde a finalização de uma busca antes de iniciar outra.
4. **Uso de Proxies Rotativos (Opcional para Grande Escala):**
   - Caso precise minerar milhares de contatos diariamente, configure proxies rotativos residenciais (ex: BrightData, Smartproxy, IPRoyal) no serviço `maps-scraper` via variável de ambiente ou arquivo de configuração do container:
   ```yaml
   environment:
     - PROXY=http://usuario:senha@ip-do-proxy:porta
   ```

### 12.3. Testes Automatizados do Scraper

```bash
# Executar a suíte de testes de Prospecção e Normalização
./venv/bin/python -m unittest tests/test_lead_scraper.py -v
```

---

> *Documento atualizado com manual completo de desenvolvimento, servidores dedicados, Coolify, Ollama IA Local, Sistema Anti-Ban / Anti-Spam WhatsApp e Prospecção Ativa Google Maps.*



