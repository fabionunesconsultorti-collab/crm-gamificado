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

### 12.3. Cancelamento e Interrupção Segura de Prospecções

Caso uma prospecção demore muito, enfrente lentidão ou tenha sido iniciada por engano, o operador pode cancelá-la a qualquer momento:

1. **Botão de Cancelamento Instantâneo:**
   - Disponível no **Card de Monitoramento ao Vivo** no topo da tela (`#liveBtnCancel`).
   - Disponível na coluna de **Ações** da tabela de histórico para qualquer busca com status `Na Fila (queued)` ou `Minerando (processing)`.
2. **Ciclo de Cancelamento no Backend:**
   - Endpoint seguro `POST /crm/prospeccao/job/<id>/cancel` com feedback visual imediato e notificação toast.
   - Envia instrução de cancelamento (`DELETE /api/v1/jobs/{id}`) para o container `maps-scraper` desalocando recursos do scraper externo.
   - A tarefa assíncrona verifica ativamente o status no banco durante o polling e nas transições de etapa, interrompendo a execução de forma graciosa sem deixar jobs travados.
   - O status é registrado como `cancelled` ("Cancelado"), salvando data e hora de encerramento (`finished_at`) e liberando a interface.

### 12.4. Testes Automatizados do Scraper

```bash
# Executar a suíte de testes de Prospecção, Normalização e Cancelamento
./venv/bin/python -m unittest tests/test_lead_scraper.py -v
```

---

## 13. Módulo de Resposta Automática Inteligente (Ollama + WAHA + Buffer Redis)

Para evitar respostas afobadas, repetitivas e desconexas quando o lead envia várias mensagens curtas em sequência (ex: *"Oi"*, *"Gostaria de saber o valor"*, *"Vocês atendem em Curitiba?"*), o CRM Pro conta com uma **arquitetura de debounce temporal e memória conversacional no Redis**.

```
Cliente WhatsApp ──> WAHA Webhook ──> Buffer Redis (RPUSH + Expire)
                                           │
                             (Aguarda janela de silêncio: ex. 12s)
                                           │
                                           ▼
                                 RQ Worker Desperta
                                           │
       ┌───────────────────────────────────┴───────────────────────────────────┐
       ▼                                   ▼                                   ▼
WAHA: Presença                Redis: Histórico Multi-turno          Ollama: /api/chat
(sendSeen + startTyping)      (Carrega turnos passados)             (Contexto Completo)
       │                                   │                                   │
       └───────────────────────────────────┬───────────────────────────────────┘
                                           ▼
                               WAHA: sendText (Resposta Unificada)
                                           ▼
                           Redis: Grava Turno na Memória (TTL 4h)
                           Postgres: Persiste MessageLog
```

### 13.1. Chaves Utilizadas no Redis

| Chave | Tipo | Finalidade | TTL |
| :--- | :--- | :--- | :--- |
| `crm:wa:buffer:{chat_id}` | `List` | Mensagens pendentes recebidas dentro da janela atual. | 1 hora |
| `crm:wa:timer:{chat_id}` | `String` | Token único da janela ativa (`batch_token`). Se novas mensagens chegarem, o token é atualizado e o job anterior é descartado. | 5 minutos |
| `crm:wa:lock:{chat_id}` | `String` | Mutex lock atômico distribuído (`SET NX EX 45`) para evitar concorrência entre workers. | 45 segundos |
| `crm:wa:history:{chat_id}` | `List` | Histórico dos últimos $N$ turnos de diálogo (`user` e `assistant`) formatados para o Ollama. | 4 horas (configurável) |
| `crm:wa:processed:{msg_id}` | `String` | Deduplicação atômica de mensagens repetidas do WAHA. | 10 minutos |

### 13.2. Parâmetros Configuráveis no Painel Administrativo

No menu **Admin -> Configurações -> Inteligência Artificial**:
- **Janela de Silêncio / Debounce (`whatsapp_debounce_delay`)**: Tempo em segundos que o sistema aguarda após a última mensagem antes de iniciar a resposta (Padrão: `12s`).
- **Turnos de Memória no Contexto (`whatsapp_history_turns`)**: Quantidade máxima de interações anteriores enviadas ao Ollama (Padrão: `8`).
- **Retenção da Memória no Redis (`whatsapp_history_ttl_hours`)**: Tempo em horas até que a conversa expire e inicie uma nova sessão (Padrão: `4h`).
- **Simular "Digitando..." (`whatsapp_simulate_typing`)**: Ativa status de digitação nativo no WhatsApp enquanto o Ollama processa a resposta.

### 13.3. Testes Automatizados do Módulo

```bash
# Executar a suíte de testes de Buffer, Debounce e Memória Conversacional
./venv/bin/python -m unittest tests/test_whatsapp_buffer.py -v

# Executar a suíte de testes de Webhook Assíncrono
./venv/bin/python -m unittest tests/test_async_webhook.py -v

# Executar a suíte de testes da Tela em Tempo Real e Simulador
./venv/bin/python -m unittest tests/test_bot_live.py -v
```

### 13.4. Interface Visual do Fluxo em Tempo Real & Simulador Live Sandbox

Acesse pelo menu lateral **Administração -> Fluxo IA do Bot** (`/admin/bot/live`):
1. **Grafo de 6 Etapas Animadas:**
   - **Etapa 1:** Webhook WAHA (Recepção instantânea).
   - **Etapa 2:** Buffer & Debounce Redis (Agrupando frases picadas e reiniciando o timer).
   - **Etapa 3:** Montagem de Contexto (Histórico multi-turno + dados cadastrais do Lead no CRM).
   - **Etapa 4:** Presença WAHA (Confirmação de leitura e simulação de *digitando...*).
   - **Etapa 5:** Inferência Ollama (Geração local do texto com o modelo configurado).
   - **Etapa 6:** Envio WhatsApp & Gravação de Memória (Despacho final e auditoria MessageLog).
2. **Simulador WhatsApp Integrado:**
   - Permite enviar mensagens de teste direto na tela sem necessidade de celular.
   - Botão **"Simular Rajada Rápida (3 msgs)"** para demonstrar o agrupamento temporal no Redis e contagem regressiva ao vivo.
### 13.5. Painel Ergonômico de Configurações do Bot (`/admin/settings?tab=bot`)

A aba **Bot de Resposta Automática** foi totalmente reprojetada com layout fluido e responsivo de **duas colunas amplas**, eliminando restrições de espaço e oferecendo controles modernos:

- **Hero Banner Interativo:** Status em tempo real do robô (Ativo/Pausado), resumo operacional e atalho direto para o *Fluxo em Tempo Real*.
- **Coluna 1 (Diretrizes Cognitivas & Atendimento):**
  - **Persona & Identidade da Marca:** Nome do assistente e nome da empresa.
  - **Prompt Mestre (System Prompt):** Editor espaçoso com botões rápidos para inserção de variáveis (`[NOME]`, `[ETAPA]`, `[SEGMENTO]`, `[VENDEDOR]`, `[EMPRESA]`, `[PERSONA]`), botão *Aprimorar Prompt com IA* e mensagem de segurança/fallback.
  - **Transbordo para Atendente Humano:** Palavras-chave gatilho e mensagem de transbordo.
  - **Horário Comercial & Expediente:** Restrição por faixa horária de expediente com mensagem de ausência personalizada.
- **Coluna 2 (Mecanismos Técnicos, Buffer Redis & Automação):**
  - **Operação & Escopo:** Ativação global, filtro de grupos e filtro de transmissões/status.
  - **Buffer Temporal & Debounce (Redis):** Slider interativo de silêncio com marcações visuais de recomendação (3s, 12s-15s, 60s) e badge de tempo em segundos dinâmico.
  - **Memória Conversacional Multi-Turno:** Controle de turnos e retenção TTL em horas no Redis.
  - **Presença & Humanização:** Confirmação de leitura (Check azul) e simulação de *digitando...* no WAHA.
  - **Integração com CRM:** Auto-cadastro de novos leads e injeção do histórico/etapa do funil no contexto da IA.
- **Barra de Ação Flutuante:** Botão de salvamento persistente acessível em qualquer rolagem.
- **Diagnóstico do Redis:** Ferramenta dedicada para limpeza segura de cache de teste, sem afetar dados reais de clientes e leads.

---

## 14. Central de Backup, Restauração e Integração com Nuvem (Google Drive)

Para garantir a **preservação perpétua e consistência absoluta dos dados de clientes, leads, mensagens e configurações**, o CRM Pro inclui um subsistema completo de backup e recuperação de desastres.

### 14.1. Isolamento de Banco e Proteção Contra Perda de Dados
- **Isolamento de Testes Unitários:** Todos os testes automatizados executam exclusivamente em instâncias voláteis de SQLite em memória (`TestConfig` com `sqlite:///:memory:`). O banco de dados PostgreSQL principal de produção/desenvolvimento (`crm_db`) está **100% blindado contra operações de `db.drop_all()` ou deleções acidentais**.
- **Transações Atômicas de Restauração:** O processo de restauração roda sob transações seguras do SQLAlchemy com rollback automático em caso de falha.
- **Ajuste Automático de Sequences:** Após qualquer importação, as sequências de auto-incremento do PostgreSQL são sincronizadas automaticamente com o maior ID existente (`SELECT setval(...)`), garantindo que novas inserções não sofram colisões de chave primária.

### 14.2. Recursos da Aba "Backup & Restauração" (`/admin/settings?tab=backup`)

1. **Backup Manual Completo em 1 Clique:**
   - Exporta todas as 10 tabelas do sistema (`User`, `Store`, `WahaInstance`, `Setting`, `MessageTemplate`, `FileMappingTemplate`, `Client`, `ScrapingJob`, `MessageLog`, `SystemLog`).
   - Salva em arquivo padronizado compactado com GZIP (`backup_crm_YYYY-MM-DD_HH-MM-SS.json.gz`) no diretório seguro `backups/`.
   - Opção para enviar simultaneamente ao Google Drive.

2. **Restauração de Dados com Validação de Integridade:**
   - Suporte a upload direto de arquivos `.json.gz` e `.json`.
   - Opção de restauração imediata a partir de qualquer backup local armazenado no servidor com um clique.

3. **Gerenciador de Backups Locais no Servidor:**
   - Lista detalhada de todos os backups salvos em disco com data, tamanho formatado e opções de:
     - 📥 **Download:** Baixar o arquivo de backup para o computador do usuário.
     - ⏱️ **Restaurar:** Reverter o banco para o estado daquele backup específico.
     - 🗑️ **Excluir:** Remover backups desnecessários para liberar espaço.

4. **Agendamento Automático (Rotina Programada):**
   - **Frequência:** Diária ou Semanal (aos domingos).
   - **Horário Programável:** Execução no horário de menor movimento (padrão `03:00` da madrugada).
   - **Política de Retenção:** Limpeza automática de arquivos locais com mais de $N$ dias (padrão `7` dias).
   - **Thread Daemon:** Execução autônoma contínua em segundo plano via `app.tasks.backup_scheduler`.

5. **Sincronização em Nuvem com Google Drive (Google Drive API v3):**
   - Conexão corporativa nativa via **Service Account (Conta de Serviço)**.
   - Parâmetros configuráveis pelo painel:
     - Ativação geral (`gdrive_enabled`).
     - ID da Pasta de destino (`gdrive_folder_id`).
     - Chave JSON da Service Account (`gdrive_credentials_json`).
   - Botão interativo **"Testar Conexão com Google Drive"** com diagnóstico em tempo real.
   - Registro de telemetria da última sincronização (`gdrive_last_status`).

---

---

## 15. Arquitetura de Captura Ativa e Despacho Autônomo do Bot WhatsApp

Para que o bot entre em ação **imediatamente e de forma totalmente autônoma** ao receber qualquer mensagem no WhatsApp conectado ao WAHA, o sistema conta com uma esteira de captura em tempo real que não depende de workers RQ externos ou rotinas manuais:

```mermaid
sequenceDiagram
    autonumber
    actor Cliente as Contato / WhatsApp
    participant WAHA as WAHA Container (Porta 3000)
    participant Flask as Backend Flask (Webhook /api/webhook/whatsapp)
    participant Redis as Redis Buffer & Lock
    participant Ollama as Ollama IA Local (Porta 11434)
    participant Live as LiveTracker (Monitor Web)

    Cliente->>WAHA: Envia mensagem no WhatsApp
    WAHA->>Flask: POST /api/webhook/whatsapp (Payload com from, body, id)
    Flask->>Redis: Salva mensagem no buffer (LPUSH) e define token de lote
    Flask->>Live: Emite evento 'webhook_received' e inicia contagem regressiva
    Flask->>Flask: Agenda Dispatcher Autônomo (threading.Timer com delay configurado)
    Note over Flask,Redis: Janela de debounce (ex: 12s de silêncio) consolida múltiplas mensagens
    Flask->>Redis: Timer expira: Valida se o batch_token ainda é o ativo e adquire lock
    Flask->>Redis: Extrai todas as mensagens acumuladas no lote
    Flask->>WAHA: Ativa presença: Marca como lida (seen) e inicia 'digitando...'
    Flask->>Redis: Carrega histórico multi-turno do cliente
    Flask->>Ollama: POST /api/chat (Contexto + Histórico + Dados CRM, num_predict=160)
    Ollama-->>Flask: Retorna resposta sintetizada rápida (~5s)
    Flask->>WAHA: POST /api/sendText com a resposta personalizada
    WAHA->>Cliente: Entrega mensagem no WhatsApp
    Flask->>Redis: Registra turno na memória conversacional
    Flask->>Flask: Grava MessageLog auditável com ID da instância
    Flask->>Live: Emite 'waha_dispatched' e finaliza o ciclo no painel gráfico
```

### 15.1. Pilares da Confiabilidade de Captura:
1. **Garantia de Webhook no WAHA (`WahaAPI.ensure_webhook`):**
   - Configurado no `docker-compose.yml` (`WHATSAPP_HOOK_URL=http://172.18.0.1:5000/api/webhook/whatsapp`).
   - Sincronização automática na inicialização da aplicação (`create_app`) e ao salvar configurações.
   - Atualização automática via `PUT /api/sessions/{session}` com eventos `['message', 'message.any']`.
2. **Dispatcher Autônomo em Thread (`_schedule_autonomous_fallback`):**
   - Cada mensagem recebida agenda um timer daemon em background no Python.
   - Ao término da janela de debounce configurada, o timer valida o `batch_token` no Redis e processa o lote automaticamente, funcionando com 100% de autonomia mesmo quando nenhum worker externo do RQ estiver rodando.
3. **Controle de Tokens e Performance na IA:**
   - Adicionado parâmetro `num_predict: 160` na geração do Ollama, garantindo respostas rápidas em celular (5 a 10 segundos) sem extrapolar timeouts.
4. **Resolução de Chaves Primárias no Banco:**
   - Tratamento universal para converter instâncias passadas por nome de sessão (ex: `'default'`) para as PKs numéricas inteiras do PostgreSQL em `MessageLog.waha_instance_id`.

---

---

## 16. Enriquecimento Contínuo de Leads e Precisão Cadastral via WhatsApp

O CRM conta com o módulo [`app/utils/lead_enricher.py`](file:///home/fabio/Projetos/CRM/app/utils/lead_enricher.py) (`LeadEnricher`), responsável por garantir máxima precisão cadastral e preenchimento progressivo de leads durante as interações com o bot autônomo.

```mermaid
flowchart TD
    Msg[Mensagem Recebida no WhatsApp] --> ExtractData[Captura de PushName e Telefone Limpo]
    ExtractData --> FindClient{Cliente Existe no CRM?}
    FindClient -- Não --> AutoCreate[Auto-Cadastro com Telefone Formatado (DD) 9XXXX-XXXX e PushName Higienizado]
    FindClient -- Sim --> Enrich[Extração Heurística de Entidades do Texto]
    AutoCreate --> Enrich
    Enrich --> CheckData{Faltam Dados Essenciais?\nNome, E-mail, Segmento}
    CheckData -- Sim --> PromptQualif[Injeta Checklist de Qualificação no Prompt da IA\n'1 Pergunta por Turno']
    CheckData -- Não --> PromptRegular[Prompt Regular de Vendas e Negociação]
    PromptQualif --> Ollama[Geração de Resposta Consultiva com Pergunta Suave]
    PromptRegular --> Ollama
    Ollama --> Send[Envio via WAHA e Atualização Cumulativa sem Perda de Dados]
```

### 16.1. Componentes de Precisão Cadastral:
1. **Normalização e Desduplicação de Telefones (`find_client_by_phone`):**
   - Extrai dígitos limpos sem sufixos (`@c.us`, `@s.whatsapp.net`, `:1`).
   - Busca em múltiplas camadas para compatibilidade com leads importados por planilhas ou cadastrados manualmente:
     - Igualdade exata (formato mascarado ou dígitos limpos).
     - Sufixo de 9 dígitos (DDD móvel).
     - Sufixo de 8 dígitos com desempate por DDD.
   - Formatação visual padronizada no padrão brasileiro: `(DD) 9XXXX-XXXX` ou `(DD) XXXX-XXXX`.
2. **Higienização de PushName (`extract_clean_push_name`):**
   - Remove emojis, decorações, símbolos e caracteres invisíveis.
   - Remove sufixos comuns do WhatsApp (ex: `"Carlos | Vendas"` vira `"Carlos"`).
   - Valida se é um nome real e legível antes de registrar no banco.
3. **Extração Contextual de Entidades (`extract_entities_from_text`):**
   - E-mails válidos (`RFC 5322`).
   - CPFs e CNPJs com formatação ou numéricos.
   - Nomes declarados espontaneamente ("meu nome é...", "sou a...") ou em resposta direta à pergunta do bot ("qual o seu nome?").
   - Segmento de mercado e área de atuação ("trabalho com...", "sou do ramo de...").
4. **Preenchimento Cumulativo e Inviolabilidade dos Dados (`enrich_client_record`):**
   - **Regra de Ouro:** NUNCA apaga ou substitui dados preexistentes.
   - Se um dado novo é fornecido (ex: e-mail), é gravado no campo correspondente.
   - Anotações (`notes`) preservam o histórico anterior e recebem carimbo de data/hora com o que foi coletado (`[DD/MM/YYYY HH:MM] Bot Coletou: ...`).
   - Leads com nome real e dados de contato são promovidos automaticamente para o status `'contato'`.
5. **Diálogo Consultivo de Qualificação Progressiva (`build_qualification_prompt_context`):**
   - O System Prompt da IA recebe um checklist transparente do que já foi preenchido e qual é o próximo dado faltante.
   - A IA é orientada a primeiro responder à dúvida do cliente e, ao final, fazer **uma única pergunta natural** para obter o dado faltante sem parecer um formulário rígido.

---

## 17. Sistema de Busca Inteligente, Filtros de Atributos e Melhorias no Cadastro de Clientes

Para agilizar a gestão de milhares de contatos e fornecer controle operacional rápido sobre o funil de vendas, foram implementados sistemas modernos de **busca inteligente instantânea** e **filtros por atributos principais** tanto na listagem de clientes quanto no quadro Kanban, além de melhorias no formulário de cadastro.

### 17.1. Melhorias na Tela de Cadastro e Edição de Clientes (`/crm/client/new` & `/crm/client/<id>/edit`)
- **Autocompletar de CEP em Tempo Real (ViaCEP):** Ao preencher os 8 dígitos do CEP, uma requisição assíncrona consulta a API ViaCEP, preenche automaticamente rua, bairro, cidade e UF, atualiza o mapa embutido do Google Maps e exibe feedback visual com sucesso.
- **Máscara Inteligente de Telefone:** Formatação dinâmica automática `(XX) 9XXXX-XXXX` para celulares e `(XX) XXXX-XXXX` para números fixos, com indicador de integridade do número.
- **Detecção e Validação de CPF/CNPJ:** Formatação automática em tempo real com identificador visual do tipo de documento informado.
- **Sugestões Rápidas de Segmento:** Input com `<datalist>` e botões/chips rápidos clicáveis (ex: *Restaurante*, *Padaria*, *Varejo*, *Saúde / Clínica*, *Estética*, *Imobiliária*, *Tecnologia*, *Automotivo*) para padronização cadastral com 1 clique.
- **Ações Rápidas Integradas:** Atalho para abrir conversa direta no WhatsApp com o número informado.

### 17.2. Busca Inteligente e Filtro por Atributos na Gestão de Clientes (`/crm/clients`)
- **Barra de Chips Rápidos de Status:** Contadores dinâmicos no topo para filtragem imediata em 1 clique (*Todos os Leads*, *Novos Leads*, *Em Contato*, *Proposta Enviada*, *Vendas Fechadas*, *Perdidos*).
- **Busca Inteligente Híbrida:** Pesquisa simultânea por Nome, Telefone, E-mail, CPF/CNPJ, Segmento, Instagram, Website e Anotações. Filtra instantaneamente no navegador enquanto o usuário digita e suporta requisições via parâmetros GET para compartilhamento de URL.
- **Painel de Atributos Avançados:** Filtros combinados por:
  - **Etapa do Funil (Status)**
  - **Segmento / Ramo de Atuação** (carregado dinamicamente do banco de dados)
  - **Vendedor Responsável** (`assigned_to` / `referred_by`)
  - **Origem do Cadastro** (Google Maps Outbound, Loja Física, E-commerce, Instagram, Indicação)
  - **Nível / Tier** (Bronze, Prata, Ouro, VIP)
  - **Data de Cadastro** (Hoje, Últimos 7 dias, Últimos 30 dias, Qualquer data)
- **Tabela Enriquecida:** Avatares com iniciais coloridas, tags de segmento e origem, links diretos para WhatsApp e Instagram, e ações rápidas de edição e disparo.

### 17.3. Busca e Filtro em Tempo Real no Funil Kanban (`/crm/kanban`)
- **Filtro Instantâneo das 5 Colunas:** Campo de busca e seletores de segmento, vendedor, origem e tier no topo do Kanban.
- **Contadores de Coluna Vivos:** O badge numérico de cada etapa (*Novos Leads*, *Em Contato*, *Proposta*, *Fechado*, *Perdido*) recalcula dinamicamente conforme os filtros são aplicados, exibindo mensagem amigável quando nenhum card bater com a busca em uma etapa específica.
- **Drag & Drop Preservado:** Mover cards entre colunas continua funcionando normalmente com os filtros ativos, com atualização persistente via AJAX e recalculo de contagens.

### 17.4. Redefinição do Padrão de Card e Layout Responsivo do Funil Kanban
- **Eliminação de Cards Desproporcionais e Quebras de Tela:**
  - Travamento rígido das colunas com `flex: 0 0 310px; width: 310px; min-width: 310px; max-width: 310px;` e scroll horizontal contínuo na `.kanban-wrap`.
  - Inclusão de `flex-shrink: 0 !important;` e `min-height: 0` nos containers internos para impedir colapso ou gigantismo dos cards em colunas com grande volume de leads.
- **Padrão Completo de Acompanhamento do Lead nos Cards:**
  - **Identificação do Lead:** Título destacado com limitação suave a 2 linhas (`-webkit-line-clamp: 2`) e quebra de palavras segura (`word-break: break-word`).
  - **Badges Estratégicos:** Selos de Nível/Tier (*VIP*, *Ouro*, *Prata*) e tags de Origem (*📍 Maps*, *📸 Insta*, *🏪 Loja*, *🛒 Web*, *🤝 Indicação*).
  - **Segmento e Avaliação:** Tag em destaque com ícone de maleta para segmento/categoria e estrelas de avaliação média do Google Maps quando disponíveis.
  - **Informações de Contato:** Telefone com ícone de clique rápido para conversa no WhatsApp e e-mail com truncamento elegante.
  - **Vendedor Responsável:** Avatar circular com inicial do consultor/vendedor atribuído e atalhos rápidos para Instagram e Website.
  - **Anotações Resumidas:** Box em itálico com citação limitada a 2 linhas, evitando que dados extensos de prospecção inflem a altura do card.
  - **Barra de Ações Padronizada:** Botões de ação uniformes (32x32px) para WhatsApp, edição de cadastro e exclusão alinhados à direita, eliminando botões esticados.

### 17.5. Otimização de Layout e Responsividade na Prospecção Ativa (`/crm/prospeccao`)
- **Proporção Perfeita de Tela e Eliminação de Transbordamento:**
  - Travamento responsivo do grid com `grid-template-columns: 300px minmax(0, 1fr)` em telas desktop (>=1024px) e empilhamento vertical suave em telas menores.
  - O contêiner de histórico e monitoramento utiliza `min-width: 0` e `table-layout: fixed;` garantindo que as 6 colunas da tabela (*ID/Data*, *Termo Pesquisado*, *Status*, *Minerados*, *Usuário*, *Ações*) fiquem 100% visíveis dentro da largura da tela sem cortes ou quebras acidentais.
- **Barra de Métricas e KPIs no Topo:**
  - Painel com 4 cartões de indicadores em tempo real: *Buscas Realizadas*, *Locais Minerados no Maps*, *Leads Inseridos no Funil* e *Status de Conexão do Docker Scraper (:8080)*.
- **Sugestões Rápidas de Nicho (Quick Chips):**
  - Botões interativos abaixo do campo de busca (*Academias*, *Lanches*, *Odonto*, *Auto Peças*, *Salões*) que preenchem instantaneamente o termo e localidade com 1 clique.
- **Barra Superior Integrada:**
  - Remoção do cabeçalho redundante; status do scraper Docker e botões de atalho (*Funil Kanban* e *Lista de Clientes*) unificados na barra superior da aplicação.

### 17.6. Padronização Visual Global e Sistema de Design Unificado em Todas as Telas
Para garantir uma experiência de usuário (UX) coesa, fluida e de alto padrão visual (*glassmorphism*, dark mode e harmonia de cores em todos os módulos), todas as telas do sistema foram refatoradas sob um mesmo padrão arquitetural e de CSS:

1. **Eliminação de Cabeçalhos Duplicados:**
   - Remoção de blocos `.header-glass` redundantes internos que repetiam o título da página.
   - Centralização de todas as ações de página, atalhos, botões primários e badges de contexto no `{% block topbar_actions %}`, injetados diretamente na barra superior global do layout (`base.html`).

2. **Componente Universal de Indicadores (`.kpi-card`):**
   - Criação de cartões métricos universais com fundo translúcido (`var(--card-bg)`), efeito de desfoque (`backdrop-filter: blur(12px)`), borda sutil (`var(--glass-border)`), ícones arredondados temáticos e tipografia destacada.
   - Implementado nos módulos: *Logs de Operação* (`/admin/logs`), *Gestão de Usuários* (`/admin/users`), *Modelos de Templates* (`/admin/templates`), *Histórico de Mensagens* (`/admin/messages`), *Dashboard Principal* (`/`), *Ranking XP* (`/ranking`), *Importação* (`/crm/import`) e *Prospecção* (`/crm/prospeccao`).

3. **Contêineres de Tabela Padronizados (`.card.table-card`):**
   - Substituição de contêineres improvisados por contêineres `.card.table-card` com cantos arredondados contínuos (`border-radius: 14px`), corte perfeito de transbordamento (`overflow: hidden`) e scroll responsivo horizontal (`.table-responsive`).
   - Padronização das tabelas de dados: *Logs de Operação*, *Usuários*, *Modelos de Mensagem*, *Histórico de Disparos*, *Clientes* e *Histórico de Prospecção*.

4. **Busca e Filtragem Instantânea Client-Side (`.search-bar-glass`):**
   - Campo de busca embutido com ícone de lupa e expansão suave no foco inserido na barra superior ou cabeçalho das tabelas.
   - Filtragem dinâmica em tempo real (sem recarregamento de página) implementada nas telas de *Logs de Operação*, *Gestão de Usuários*, *Histórico de Mensagens* e *Listagem de Clientes*.

5. **Formulários e Cartões de Ação Centralizados (`.card`):**
   - Formulários de edição/criação (*Cadastro de Usuário*, *Novo Template*, *Envio WhatsApp Avulso*, *Importação de Planilha*) agora utilizam contêineres `.card` estruturados com cabeçalho (`.card-header`), corpo com inputs translúcidos (`.input-glass`) e rodapé de ações (`.card-footer`).
   - Alinhamento ergonômico com largura controlada (`max-width: 650px`) e centralização visual na viewport.

6. **Padrão de Badges e Selos de Status:**
   - Unificação das classes `.badge-primary`, `.badge-secondary`, `.badge-success`, `.badge-warning`, `.badge-danger` e `.badge-info` com bordas translúcidas, ícones de apoio e tipografia legível em todos os temas.

---

## 25. Procedimento de Recuperação e Reinício de Captura do WhatsApp (WAHA)

### 25.1 Causa Raiz de Interrupções de Captura
O recebimento de mensagens do WhatsApp depende da cadeia contínua:
1. **Container WAHA:** A sessão WhatsApp precisa estar no estado `WORKING` (conectada ao aparelho). Caso o container seja reiniciado, caia ou perca a sessão, a API do WAHA retorna `404 Not Found` para a sessão ou a mantém em `STOPPED`/`SCAN_QR_CODE`.
2. **Subscrição de Webhook:** O WAHA precisa estar configurado com a URL correta do backend CRM (`http://172.18.0.1:5000/api/webhook/whatsapp` na rede Docker) com os eventos `message`, `message.any` e `messages.update`.
3. **Locks do Buffer Redis:** Caso uma mensagem tenha sofrido crash ou interrupção durante o debounce, chaves de lock (`crm:wa:lock:*`) podem ficar retidas temporariamente.

### 25.2 Procedimento Automatizado de Reinício (5 Etapas)
Foi implementado o método centralizado `WahaAPI.restart_whatsapp_capture(instance_id=None)` que executa um diagnóstico e reparo completo em tempo real:
1. **Validação de Conectividade:** Testa a API HTTP do WAHA na porta 3000 com resolução automática de IP (`127.0.0.1`, IP de rede local ativa ou `host.docker.internal`).
2. **Diagnóstico & Inicialização da Sessão:**
   - Se a sessão não existir (`HTTP 404`), cria a instância imediatamente com a configuração correta de webhook.
   - Se a sessão estiver `STOPPED` ou `FAILED`, envia comando `POST /api/sessions/{session}/restart` (ou `/start`).
   - Se a sessão exigir leitura do QR Code, sinaliza `SCAN_QR_CODE` para exibição imediata do código na interface.
3. **Injeção Forçada de Webhook:**
   - Envia um `PUT /api/sessions/{session}` com payload explícito contendo os webhooks do CRM, garantindo que o WAHA passe a rotear os eventos de mensagens recebidas.
4. **Desobstrução do Buffer Redis:**
   - Varre e remove travas orfãs em `crm:wa:lock:*`, permitindo que novas mensagens recebidas entrem no debounce sem bloqueios.
5. **Sincronização no CRM:**
   - Atualiza o registro local da instância no banco de dados (`connected`, `waiting_qr` ou `connecting`) e grava evento no `SystemLog` para auditoria.

### 25.3 Como Acionar o Procedimento na Interface
O procedimento pode ser acionado em 1 clique em dois locais estratégicos:
- **Central de Operações Autônomas / Bot Live (`/admin/bot/live`):**
  - Botão **"Reiniciar Recebimento"** no cabeçalho superior.
  - Botão de ação rápida no **Nó 1 (Webhook WAHA)** do grafo do pipeline.
  - Exibe modal com checklist visual em tempo real de cada etapa e atalho para escanear o QR Code se a sessão foi recriada.
- **Configurações do Sistema (`/admin/settings?tab=waha`):**
  - Banner de destaque **"Recuperação do Recebimento de Mensagens"**.
  - Botão individual **"Reiniciar Captura"** dentro de cada cartão de instância configurada.

---

## 26. Painel Avançado de Calibração e Treinamento RAG (Control Panel & Hybrid Engine)

### 26.1 Arquitetura e Objetivo
Para permitir que equipes de engenharia, produto e operações calibrem e aprimorem o comportamento do assistente virtual WhatsApp em tempo real sem necessidade de alterações no código-fonte ou redeploys, foi desenvolvida a suíte avançada de **RAG Control Panel** e o novo motor híbrido em `app/utils/rag_engine.py` e `/admin/knowledge`.

O pipeline opera em três camadas coordenadas:
1. **Recuperação Densa (Dense Vector):** Embeddings semânticos gerados localmente via Ollama com o modelo `nomic-embed-text` (dimensão 768) indexados e consultados com similaridade cosseno no ChromaDB.
2. **Recuperação Léxica (BM25 com Stopwords):** Algoritmo Okapi BM25 implementado com remoção de stopwords em língua portuguesa para casamento exato de códigos, termos técnicos e valores monetários.
3. **Fusão Híbrida com Peso Alpha ($0.0 \le \alpha \le 1.0$):**
   $$\text{Score}_{\text{Híbrido}} = \alpha \times \text{Score}_{\text{Dense}} + (1 - \alpha) \times \text{Score}_{\text{BM25}}$$
4. **Segunda Camada (Reranker & Cutoff):** Reclassificação dos melhores candidatos recuperados e filtragem por limiar mínimo de confiança antes da injeção no prompt de contexto do LLM.

```
[ Usuário WhatsApp ] ──> [ Query ] 
                             │
            ┌────────────────┴────────────────┐
            ▼                                 ▼
   [ Embeddings Ollama ]             [ Tokenizador BM25 ]
   (nomic-embed-text)               (Stopwords em PT-BR)
            │                                 │
            ▼                                 ▼
   [ Busca ChromaDB ]                 [ Match Léxico ]
      (Top-K Inicial)                 (Frequência Termo)
            │                                 │
            └────────────────┬────────────────┘
                             ▼
                [ Fusão Híbrida com Alpha ]
                             │
                             ▼
              [ Reranking & Threshold Cutoff ]
                             │
                             ▼
            [ Injeção de Contexto no LLM ]
              (Llama 3.2 com Guardrails)
```

---

### 26.2 Parâmetros Calibráveis no Painel (`/admin/knowledge`)

Os parâmetros são persistidos na tabela `Setting` e aplicados instantaneamente (*hot-reload*) no motor RAG:

| Categoria | Parâmetro | Padrão | Intervalo / Opções | Descrição & Efeito no Bot |
| :--- | :--- | :---: | :---: | :--- |
| **Chunking** | `rag_chunk_size` | `450` | `200` a `1500` chars | Tamanho de cada bloco de texto. Blocos menores aumentam a precisão tópica; blocos maiores preservam o contexto. |
| **Chunking** | `rag_chunk_overlap` | `60` | `0` a `300` chars | Sobreposição entre blocos adjacentes para evitar quebra semântica de frases ou tabelas. |
| **Chunking** | `rag_split_strategy` | `paragraph` | `paragraph`, `sentence`, `fixed` | Estratégia de corte: por parágrafo (`\n\n`), por pontuação de sentenças ou tamanho estrito. |
| **Recuperação** | `rag_search_mode` | `hybrid` | `hybrid`, `dense`, `sparse` | Modo do buscador: Híbrido (Vetorial + BM25), Somente Vetorial ou Somente BM25. |
| **Recuperação** | `rag_hybrid_alpha` | `0.70` | `0.00` a `1.00` | Peso da busca: `1.0` é 100% semântico e `0.0` é 100% léxico. O valor `0.70` equilibra significado e termos literais. |
| **Recuperação** | `rag_top_k` | `6` | `1` a `20` | Quantidade inicial de fragmentos recuperados para a fase de reclassificação. |
| **Reranking** | `rag_reranker_enabled` | `true` | `true` / `false` | Ativa a segunda camada de pontuação combinada e filtragem de ruído. |
| **Reranking** | `rag_top_n` | `3` | `1` a `10` | Quantidade final de trechos repassados na memória de contexto do LLM. |
| **Reranking** | `rag_rerank_min_score` | `0.40` | `0.00` a `1.00` | Nota mínima exigida. Fragmentos abaixo do corte são descartados para evitar alucinações. |
| **LLM & Geração** | `whatsapp_bot_temperature` | `0.30` | `0.00` a `1.50` | Criatividade da resposta. Valores baixos (0.2–0.4) garantem respostas factuais e consistentes com a base. |
| **LLM & Geração** | `rag_llm_max_tokens` | `400` | `100` a `1500` | Limite máximo de tokens gerados por resposta no WhatsApp. |
| **Segurança** | `rag_guardrails_enabled` | `true` | `true` / `false` | Habilita verificação prévia de termos proibidos na pergunta ou na resposta. |
| **Segurança** | `rag_guardrail_blacklist` | *Termos* | Lista separada por vírgula | Palavras ou temas bloqueados (ex: insultos, prompts de jailbreak, concorrência). |
| **Segurança** | `rag_fallback_msg` | *Mensagem padrão* | Texto livre | Resposta amigável quando nenhum documento relevante for localizado na base. |

---

### 26.3 Endpoints da API de Calibração e Telemetria

1. **`POST /admin/knowledge/calibrate`**
   - **Autorização:** Usuário logado com perfil de Administrador.
   - **Payload JSON:** Dicionário com chaves e valores a serem atualizados.
   - **Resposta:**
     ```json
     {
       "ok": true,
       "message": "Parâmetros do RAG atualizados com sucesso!",
       "configs": { ... }
     }
     ```

2. **`POST /admin/knowledge/calibrate/reset`**
   - Restaura instantaneamente todos os parâmetros de calibração para os valores padrões recomendados pela engenharia de IA.

3. **`GET /admin/knowledge/telemetry`**
   - Retorna métricas de performance da esteira RAG baseadas no histórico recente em memória (buffer circular com últimos 200 eventos):
     - `total_queries`: Volume de buscas realizadas.
     - `avg_latency_ms`: Tempo médio de resposta do pipeline RAG em milissegundos.
     - `hit_rate_pct`: Porcentagem de consultas que obtiveram documentos acima do score mínimo.
     - `avg_score`: Média dos scores retornados.
     - `recent_queries`: Lista das últimas consultas executadas contendo query, timestamp, latência e melhor score obtido.

---

### 26.4 Interface do Painel (`/admin/knowledge`)

A interface da Base de Conhecimento foi expandida com duas novas abas dedicadas:
- **Aba 5 - Calibração RAG / Control Panel:**
  - Controles deslizantes reativos (sliders) com atualização dinâmica de valores numéricos em tempo real.
  - Seletores ergonômicos para Estratégia de Fatiamento e Modo de Busca.
  - Alertas didáticos explicando o impacto operacional de cada ajuste.
  - Botão de ação rápida **"Salvar Calibração"** e **"Restaurar Padrões Recomendados"**.
  - Simulador integrado exibindo a decomposição visual de pontuação: **Score Híbrido**, **Dense**, **BM25** e **Rerank**.
- **Aba 6 - Métricas & Telemetria em Tempo Real:**
  - 4 KPI cards translúcidos: *Consultas Executadas*, *Latência Média (ms)*, *Taxa de Resolução (Hit Rate)* e *Score Médio*.
  - Tabela de auditoria em tempo real das últimas buscas realizadas pelo bot.

---

## 27. Plano de Modularização e Feature Flags (Arquitetura Independente de Módulos)

### 27.1 Diagnóstico Técnico do Estado Atual

A aplicação utiliza Flask Blueprints (`auth/`, `main/`, `crm/`, `admin/`, `api/`), o que é o caminho correto para modularização. Porém, todos os blueprints são registrados **incondicionalmente** na factory `create_app()` e não há nenhum mecanismo de feature flags para ligar/desligar funcionalidades de forma independente.

**Problemas de acoplamento identificados:**

| # | Problema | Arquivo(s) | Impacto |
|---|----------|------------|---------|
| 1 | **Modelo Monolítico** — 11 modelos de domínios distintos em arquivo único | `app/models.py` (451 linhas) | Impossível isolar domínios (WhatsApp, RAG, Prospecção) |
| 2 | **Imports Estáticos Cruzados** — sem guard ou fallback | `app/crm/routes.py` (importa WAHA, AI, Scraper incondicionalmente) | Se Ollama/WAHA offline, carregamento pode falhar |
| 3 | **Admin "God Object"** — arquivo de rotas excessivamente grande | `app/admin/routes.py` (1.177 linhas) | Toda alteração em qualquer área toca o mesmo arquivo |
| 4 | **Tasks Acopladas** — re-export no `__init__.py` sem proteção | `app/tasks/__init__.py` | Redis offline derruba toda a aplicação |
| 5 | **WAHA Hardcoded no Boot** — webhook init sem feature flag | `app/__init__.py` (linhas 52-65) | Sempre tenta conectar, mesmo se WhatsApp não for usado |
| 6 | **Zero Feature Flags** — nenhuma ocorrência no código | Todo o projeto | Impossível desativar funcionalidades sem alterar código |
| 7 | **Utils Catch-All** — 12 arquivos de domínios distintos | `app/utils/` | Sem encapsulamento; dependências cruzadas invisíveis |

### 27.2 Mapa de Dependências (Acoplamento Real)

```
Blueprints                    Utils (Catch-all)              Tasks
┌──────────┐                 ┌──────────────────┐           ┌──────────────────┐
│ auth/    │                 │ waha.py          │←────┐     │ whatsapp.py      │
│ main/    │                 │ ai_handler.py    │←──┐ │     │ lead_scraper.py  │
│ crm/     │──hardcoded────→ │ maps_scraper.py  │   │ │     │ buffer.py        │
│ admin/   │──hardcoded────→ │ rag_engine.py    │   │ │     │ queue.py         │
│ api/     │──hardcoded────→ │ backup_manager.py│   │ │     └───────┬──────────┘
└──────┬───┘                 │ lead_enricher.py │   │ │             │
       │                     │ live_tracker.py  │   │ │             │
       │                     │ conversation_    │   │ │             │
       │                     │   memory.py      │   │ │             │
       │                     └──────────────────┘   │ │             │
       │                                            │ │             │
       └──────────── Todos importam ────────────────┘ │             │
                     models.py (monolítico) ──────────┘             │
                     11 modelos em 1 arquivo ───────────────────────┘
```

**Todas as setas são hardcoded** — nenhuma é condicional ou desligável.

### 27.3 Teste de Impacto: O Que Quebra Se Desligar um Serviço

| Se desligar... | O que quebra | Nível de Impacto |
|----------------|--------------|:-----------------:|
| **Redis** | `tasks/__init__.py` falha no import → toda a app morre | 🔴 Crítico |
| **Ollama / IA** | WhatsApp bot, geração de mensagens, admin settings | 🟠 Alto |
| **WAHA / WhatsApp** | Init da app trava 2s; CRM routes com ImportError | 🟠 Alto |
| **ChromaDB / RAG** | Admin settings, processamento WhatsApp perde contexto RAG | 🟡 Médio |
| **Maps Scraper** | CRM routes importam incondicionalmente | 🟡 Médio |
| **PostgreSQL → SQLite** | Funciona (config trata), mas migrations podem divergir | 🟡 Médio |

### 27.4 Plano de Remediação em 5 Fases

#### Fase 1 — Feature Flags e Registry de Módulos (Esforço: ~2 dias, Risco: 🟢 Baixo)

**Objetivo:** Poder ligar/desligar qualquer módulo via configuração, sem alterar código-fonte.

**Ações:**

1. Criar arquivo `app/utils/module_registry.py` com:
   - Definição de módulos: `whatsapp`, `ai_bot`, `rag`, `prospecting`, `gamification`, `backup`
   - Função `is_module_enabled(module_name)` que lê da tabela `Setting`
   - Decorator `@requires_module('nome')` para proteger rotas
   - Função `get_all_modules()` para UI de administração

2. Chaves de feature flags na tabela `Setting`:
   ```
   module_whatsapp_enabled     = true (default)
   module_ai_bot_enabled       = true
   module_rag_enabled          = true
   module_prospecting_enabled  = true
   module_gamification_enabled = true
   module_backup_enabled       = true
   ```

3. Exemplo de uso do decorator:
   ```python
   @bp.route('/prospeccao')
   @login_required
   @requires_module('prospecting')
   def prospeccao(): ...
   ```

4. Modificar `app/__init__.py` para:
   - Inicializar WAHA/backup scheduler condicionalmente
   - Injetar `is_module_enabled` nos templates via `context_processor`
   - Invalidar cache do registry por request

5. Tornar sidebar do `base.html` condicional com Jinja:
   ```html
   {% if is_module_enabled('whatsapp') %}
   <li><a href="...">Disparo em Lote</a></li>
   {% endif %}
   ```

6. Criar painel `/admin/modules` com toggles visuais por módulo.

#### Fase 2 — Separação de Models por Domínio (Esforço: ~2 dias, Risco: 🟢 Baixo)

**Objetivo:** Cada domínio funcional possui seus próprios modelos.

**Estrutura alvo:**
```
app/models/
├── __init__.py        → re-exporta tudo (retrocompatível)
├── user.py            → User, load_user
├── client.py          → Client, Store
├── whatsapp.py        → WahaInstance, MessageLog, MessageTemplate
├── prospecting.py     → ScrapingJob
├── knowledge.py       → KnowledgeDoc
├── settings.py        → Setting
└── system.py          → SystemLog, FileMappingTemplate
```

O `__init__.py` mantém retrocompatibilidade re-exportando todos os modelos:
```python
from app.models.user import User
from app.models.client import Client, Store
from app.models.whatsapp import WahaInstance, MessageLog, MessageTemplate
# ... etc
```

#### Fase 3 — Lazy Loading e Imports Condicionais (Esforço: ~3 dias, Risco: 🟡 Médio)

**Objetivo:** Nenhum módulo falha se uma dependência externa estiver ausente.

**Ações:**

1. Proteger `tasks/__init__.py` com try/except:
   ```python
   try:
       from .queue import get_queue, get_redis_connection
   except Exception:
       get_queue = get_redis_connection = None
   ```

2. Transformar imports estáticos em lazy imports nos routes:
   ```python
   # ANTES (falha se WAHA offline)
   from app.utils.waha import WahaAPI

   # DEPOIS (graceful degradation)
   def _get_waha():
       if not is_module_enabled('whatsapp'):
           return None
       from app.utils.waha import WahaAPI
       return WahaAPI
   ```

3. Tornar init do WAHA condicional no boot da app:
   ```python
   if not app.config.get('TESTING') and is_module_enabled('whatsapp'):
       # ... init webhook
   ```

#### Fase 4 — Quebrar o Admin "God Object" (Esforço: ~3 dias, Risco: 🟡 Médio)

**Objetivo:** Cada domínio funcional tem seus próprios routes no admin.

**Estrutura alvo:**
```
app/admin/
├── __init__.py            → Blueprint + imports condicionais
├── routes.py              → Rotas base (settings gerais, dashboard)
├── routes_whatsapp.py     → WAHA instances, logs, templates
├── routes_ai.py           → Config IA, prompts, RAG
├── routes_backup.py       → Backup/Restore
├── routes_users.py        → CRUD de usuários
└── routes_theme.py        → Personalização visual
```

Cada sub-módulo registra rotas condicionalmente:
```python
# admin/__init__.py
bp = Blueprint('admin', __name__)
from app.admin import routes  # sempre

if is_module_enabled('whatsapp'):
    from app.admin import routes_whatsapp
if is_module_enabled('ai_bot'):
    from app.admin import routes_ai
```

#### Fase 5 — Reorganizar em Packages por Domínio (Esforço: ~2 dias, Risco: 🔴 Alto)

**Objetivo:** Cada módulo funcional é auto-contido com seus modelos, rotas, tasks e utilitários.

**Estrutura alvo:**
```
app/
├── modules/
│   ├── whatsapp/
│   │   ├── __init__.py
│   │   ├── models.py       → WahaInstance, MessageLog, MessageTemplate
│   │   ├── api.py          → WahaAPI
│   │   ├── tasks.py        → process_whatsapp_message, buffer
│   │   ├── routes.py       → Webhook endpoints
│   │   └── memory.py       → ConversationMemory
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── handler.py      → AIHandler
│   │   ├── rag_engine.py   → RAGEngine
│   │   └── models.py       → KnowledgeDoc
│   ├── prospecting/
│   │   ├── __init__.py
│   │   ├── scraper.py      → MapsScraperClient
│   │   ├── tasks.py        → dispatch_scraping_job
│   │   └── models.py       → ScrapingJob
│   ├── gamification/
│   │   ├── __init__.py
│   │   ├── engine.py       → award_xp, leaderboard
│   │   └── constants.py    → XP values
│   └── backup/
│       ├── __init__.py
│       ├── manager.py      → BackupManager
│       └── scheduler.py    → Cron de backup
├── core/
│   ├── models.py           → User, Client, Store, Setting, SystemLog
│   ├── auth/               → Blueprint de auth
│   └── exports.py          → CSV/PDF
```

### 27.5 Ordem de Prioridade Recomendada

| Prioridade | Fase | Risco Regressão | Valor Imediato |
|:---:|---|:---:|---|
| 🥇 | **Fase 1** — Feature Flags | 🟢 Baixo | Desligar módulos sem deploy |
| 🥈 | **Fase 3** — Lazy Loading | 🟡 Médio | App não morre com Redis/Ollama offline |
| 🥉 | **Fase 2** — Models separados | 🟢 Baixo | Manutenção e clareza |
| 4 | **Fase 4** — Admin split | 🟡 Médio | Redução de complexidade |
| 5 | **Fase 5** — Packages por domínio | 🔴 Alto | Arquitetura limpa de longo prazo |

> **Nota:** As Fases 1 e 3 podem ser feitas sem refatoração estrutural e dão o maior ganho de resiliência. As Fases 4 e 5 são refatorações mais profundas que devem ser feitas com suite de testes robusta.

### 27.6 Métricas de Acoplamento (Antes vs. Meta)

| Métrica | Valor Atual | Meta Ideal |
|---|:---:|:---:|
| Modelos por arquivo | 11 em 1 | 2-3 por arquivo |
| Linhas no admin/routes.py | 1.177 | < 200 por arquivo |
| Feature flags | 0 | 6+ |
| Imports condicionais | 0 | 15+ |
| Módulos desligáveis independentemente | 0 | 6 |
| Blueprints condicionais | 0 de 5 | 3 de 5 |

---

---

## 28. Correção e Normalização de Telefones & Resolução de LIDs do WhatsApp

### 28.1 Contexto e Diagnóstico do Problema
Anteriormente, a captura automática de contatos via webhook e scraping apresentava inconsistências críticas:
1. **LIDs do WhatsApp (`@lid`)**: O WhatsApp Web / Multi-Device moderno frequentemente entrega identificadores de dispositivo (ex: `71674514952338@lid`) em vez do JID padrão (`5519998...`). A rotina anterior extraía apenas os dígitos crus, cadastrando o LID de 14–16 dígitos no campo `phone`, impossibilitando o disparo ou abertura de conversas.
2. **Canais e Newsletters (`@newsletter`)**: Mensagens de canais (`120363...@newsletter`) eram tratadas como mensagens de clientes, gerando auto-cadastros falsos (ex: `Lead WA 3742` com telefone `120363404701403742`).
3. **Duplicação de DDI `55` em Links**: Nos templates e rotas de mensagem, links do tipo `https://wa.me/55{{ client.phone }}` duplicavam o DDI para telefones que já continham `55` (ficando `5555...`), ou geravam links sem DDI quando o telefone não o continha.
4. **Múltiplos Telefones no Google Maps**: Estabelecimentos comerciais com telefones concatenados por barra (`/`, `|` ou `,`) tinham seus dígitos somados em números de 18 a 22 dígitos e eram descartados pela validação.

### 28.2 Solução Implementada

1. **Resolução de Contatos via WAHA (`WahaAPI.resolve_contact_phone`)**:
   - Quando um identificador for `@lid` ou não for um telefone nacional válido, a API do WAHA (`GET /api/{session}/contacts/{id}`) é consultada em tempo real para obter o número real (`@c.us`), o nome registrado e o `pushName`.
   - Se o número não for resolúvel ou for um grupo/canal, o sistema impede a criação de leads corrompidos.  
2. **Filtro Estrito no Webhook (`app/api/routes.py`)**:
   - Rejeição imediata de eventos originados de `@newsletter`, prefixos `120363` e grupos `@g.us` no auto-cadastro.
3. **Propriedades Seguras no Modelo `Client` (`app/models.py`)**:
   - `client.whatsapp_url`: Retorna a URL oficial `https://wa.me/55...` com garantia de DDI 55 único (sem duplicações).
   - `client.whatsapp_chat_id`: Retorna o formato exato esperado pela API do WAHA (`55...c.us`).
   - `client.formatted_phone`: Formatação legível brasileira `(DD) 9XXXX-XXXX`.
   - `client.clean_phone`: Apenas os dígitos válidos.
4. **Tratamento de Múltiplos Números na Prospecção Ativa (`app/tasks/lead_scraper.py`)**:
   - Divide números múltiplos por separadores (`/`, `|`, `,`, `;`), herda o DDD do primeiro telefone caso os seguintes sejam locais e prioriza celulares com nono dígito.
5. **Correção e Saneamento da Base de Dados**:
   - Leads pré-existentes gravados com identificadores LID foram devidamente convertidos para seus números reais de WhatsApp e nomes da agenda, e registros espúrios de canais de newsletter foram removidos.

---

## 31. Skills & Diretrizes de Atendimento Prioritárias no RAG (Priority Chunks & Conduct Control)

### 31.1 Conceito e Arquitetura de Priorização
Diferente dos documentos puramente informativos (como manuais, contratos ou tabelas de preços), os **Skills de Atendimento** representam orientações estratégicas sobre **como o bot deve se comportar e conduzir a comunicação** no WhatsApp (ex: técnicas de fechamento, contorno de objeções, tom de voz empático, qualificação BANT).

Para garantir que essas diretrizes não sejam sufocadas ou desconsideradas durante a recuperação do RAG, a arquitetura foi aprimorada com três mecanismos de priorização:

1. **Skill Domain Boosting (+0.18 no Reranking):**
   - No motor `RAGEngine.search_relevant_snippets()`, trechos cadastrados sob a categoria/tipo `skill` (ou contendo palavras como `habilidade`, `diretriz`, `conduta`, `objecao`, `fechamento`, `postura`) recebem um bônus prioritário de **+0.18** no score final do reranker, garantindo sua presença entre os trechos recuperados.
2. **Particionamento Estruturado de Contexto (`RAGEngine.get_structured_context`):**
   - O motor divide automaticamente os fragmentos resgatados em dois grupos distintos:
     - `skills_text`: Trechos de postura, tom de voz e técnica de vendas;
     - `official_text`: Dados oficiais de produtos, regras operacionais e preços.
3. **Injeção Prioritária no Prompt de Sistema (`AIHandler.generate_chat_reply`):**
   - Os skills de atendimento recuperados são injetados em um bloco exclusivo de alta visibilidade no prompt do LLM:
     `🎯 SKILLS & DIRETRIZES DE ATENDIMENTO PRIORITÁRIAS (CONDUTA E TÉCNICA DE VENDAS)`
   - O prompt impõe ao modelo a **Diretiva de Postura**, obrigando-o a adotar a conduta e técnica especificada durante a resposta.

### 31.2 Cadastro e Templates Prontos no Painel (`/admin/knowledge`)
- **Aba Dedicada:** Aba **"5. Skills de Atendimento (Prioritários)"** no painel administrativo.
- **Rota `POST /admin/knowledge/skill`:** Grava o documento com `doc_type='skill'`, fatiando e indexando no ChromaDB.
- **Templates de Skills em 1 Clique:**
  - ⚡ **Contorno de Objeção (Preço/Concorrência):** Acolhimento empático, demonstração de ROI e comparativo de diferenciais exclusivos;
  - ⚡ **Técnica de Fechamento Soft:** Condução positiva para a próxima ação de avanço no funil (agendamento ou cadastro);
  - ⚡ **Atendimento Empático & Tom de Voz:** Parágrafos curtos, escuta ativa e tratamento personalizado no WhatsApp;
  - ⚡ **Qualificação de Necessidades (BANT):** Perguntas de sondagem prévia para identificar gargalos do lead.
- **Selo Visual `🎯 SKILL`:** Destaque em âmbar translúcido na tabela de auditoria de conhecimento.

---

## 32. Central de Integrações e Módulo ERP Bling (Arquitetura Desacoplada & Plugin Framework)

### 32.1 Arquitetura Desacoplada (Integration Plugin Framework)
Para permitir que o CRM se conecte a diferentes ERPs e plataformas sem acoplamento rígido, foi implementado o motor **`IntegrationManager`** baseado no padrão **Adapter + Feature Flag**:

1. **Abstração Base (`BaseIntegrationAdapter`):** Interface padronizada em `app/integrations/base.py` para gerenciamento de status, logs, testes de conexão e sincronização de clientes/vendas.
2. **Gerenciador Central (`IntegrationManager`):** Registro dinâmico de adaptadores em `app/integrations/manager.py`. Permite ligar (ON) ou desligar (OFF) cada integração via painel administrativo.
3. **Persistência de Dados & Mapeamento Universal:**
   - `integration_config`: Tabela para armazenar estado ON/OFF, autenticação (OAuth2/API Key), tokens e configurações em JSON.
   - `external_entity_map`: Mapeamento universal de IDs (`crm_entity_id` <-> `external_id`) por provedor.
   - `bling_sales_cache`: Cache local de pedidos de venda do Bling ERP para aceleração de dashboards sem rate-limit.
   - `integration_log`: Histórico e auditoria de execuções.

### 32.2 Funcionalidades do Módulo Bling ERP
- **Sincronização Bi-direcional de Clientes (Puxar / Subir):**
  - **Inbound (Bling ➔ CRM):** Puxa contatos da API v3 do Bling com deduplicação por CPF/CNPJ, Telefone formatado e E-mail.
  - **Outbound (CRM ➔ Bling):** Exporta clientes do CRM para o Bling individualmente ou em lote.
- **Bling Analytics & Dashboards (`/integrations/bling/dashboard`):**
  - Gráficos interativos (Chart.js) com a **Curva ABC de Clientes Top 10** e **Distribuição de Pedidos por Status**.
  - KPIs em tempo real (Faturamento Total, Ticket Médio, Total de Pedidos e Clientes Sincronizados).
  - Tabela de vendas com filtro instantâneo e exportação para **CSV**.
- **Central de Administração (`/integrations/admin`):**
  - Switch Toggle ON/OFF por provedor.
  - Modal de configuração para OAuth 2.0 Client ID/Secret, Access Token e API Key.
  - Botão de teste de conexão em 1 clique e histórico de logs.

### 32.3 Guia Passo a Passo do Desenvolvedor: Como Adicionar Novas Integrações (ex: Tiny ERP, Shopify, WooCommerce, Hubspot)

Para adicionar qualquer nova integração no CRM mantendo o isolamento desacoplado, o desenvolvedor deve seguir este fluxo em 4 passos simples:

#### Passo 1: Criar a pasta do provedor
Crie o diretório `app/integrations/<provedor>/` (ex: `app/integrations/tiny/` ou `app/integrations/shopify/`).

#### Passo 2: Implementar a classe Adapter estendendo `BaseIntegrationAdapter`
Crie o arquivo `app/integrations/<provedor>/adapter.py` com a classe estendendo `BaseIntegrationAdapter` e decorada com `@IntegrationManager.register`:

```python
from app.integrations.base import BaseIntegrationAdapter
from app.integrations.manager import IntegrationManager

@IntegrationManager.register
class TinyAdapter(BaseIntegrationAdapter):
    provider_name = "tiny"
    display_name = "Tiny ERP"
    description = "Integração desacoplada com Tiny ERP para sincronização de clientes e vendas."

    def test_connection(self) -> dict:
        # Lógica de teste de conexão com a API do Tiny
        config = self.get_config()
        # ... realiza requisição HTTP de teste ...
        return {"success": True, "message": "Conexão com Tiny ERP realizada com sucesso!"}

    def sync_clients_inbound(self, limit: int = 100) -> dict:
        # Importa contatos do Tiny e salva no CRM (Client + ExternalEntityMap)
        return {"success": True, "message": "Importação concluída com sucesso."}

    def sync_clients_outbound(self, client_id=None) -> dict:
        # Exporta contatos do CRM para o Tiny
        return {"success": True, "message": "Exportação para o Tiny concluída."}

    def fetch_sales_reports(self, start_date=None, end_date=None) -> dict:
        # Consulta pedidos de venda do Tiny e salva em cache
        return {"success": True, "message": "Relatórios de venda atualizados."}
```

#### Passo 3: Registrar o import em `app/integrations/__init__.py`
Adicione o import do novo adaptador ao final de `app/integrations/__init__.py`:
```python
import app.integrations.tiny.adapter
```

#### Passo 4: Reconhecimento Automático e Interface Pronta
Ao inicializar o CRM:
1. O `IntegrationManager` detecta a nova integração automaticamente.
2. O card do **Tiny ERP** é renderizado no painel `/integrations/admin` com botão **Switch Toggle (ON/OFF)**, modal de credenciais, teste de conexão e logs de auditoria.
3. Se o administrador desligar a chave, a função fica 100% inativa sem impactar nenhuma outra área do sistema.

---

## 28. Plano Diretor de Refatoração Faseada por Setores & Arquitetura de Plugins Desligáveis

### 28.1 Diretrizes e Reorganização por Setores

Para garantir manutenibilidade a longo prazo, isolamento de falhas e expansão desacoplada, a aplicação foi reavaliada e dividida formalmente em **5 Setores Funcionais**:

```
                       ┌──────────────────────────────────────────┐
                       │          app/core / Flask App            │
                       └────────────────────┬─────────────────────┘
                                            │
        ┌───────────────────┬───────────────┼───────────────┬───────────────────┐
        │                   │               │               │                   │
  ┌─────▼─────────────┐ ┌───▼───────────┐ ┌─▼─────────────┐ ┌▼───────────────┐ ┌─▼─────────────┐
  │ Gestão de Clientes│ │ IA & Automação│ │ Configuração  │ │  Integrações   │ │    Plugins    │
  │ (gestao_clientes) │ │ (ia_automacao)│ │(configuracao) │ │ (integracoes)  │ │(motor_plugins)│
  └───────────────────┘ └───────────────┘ └───────────────┘ └───────────────┘ └───────────────┘
```

#### Estrutura Detalhada por Setor:

1. **Gestão de Clientes (`gestao_clientes`)**
   - **Módulos**: Funil Kanban (`funnel`), Cadastro & Lead Scoring (`clients`), Prospecção Google Maps (`prospecting`), Tarefas & Lembretes (`tasks`), Gamificação & Ranking (`gamification`).
   - **Independência**: Cada sub-módulo pode ser ligado/desligado individualmente sem afetar as rotas de clientes principais.

2. **IA e Automação (`ia_automacao`)**
   - **Módulos**: Conectores LLM (`llm_providers`), Engine RAG Vectorial (`rag_engine`), TensorFlow Local Neural (`tf_engine`), Auto-Responder Bot (`auto_responder`), Minerador FAQ (`faq_miner`).
   - **Isolamento de Falhas**: Se a IA estiver offline ou desativada, a plataforma continua operando normalmente como CRM tradicional.

3. **Configuração (`configuracao`)**
   - **Módulos**: Parâmetros Globais (`system_settings`), Regras Anti-Ban WhatsApp (`antiban`), Backups Automáticos (`backups`), Personalizador HSL (`ui_theme`), Logs & Auditoria (`audit_logs`).

4. **Integrações (`integracoes`)**
   - **Módulos**: Gateway WhatsApp (`waha`), ERP Bling (`bling`), Receptor/Disparador de Webhooks (`webhooks`).
   - **Desacoplamento**: Todas as integrações herdam de `BaseIntegrationAdapter` e respondem ao `IntegrationManager`.

5. **Plugins (`motor_plugins`)**
   - **Módulos**: Registry de Plugins (`plugin_registry`), Barramento de Eventos (`event_bus`), Gerenciador de Hooks (`hook_manager`).
   - **Diretriz Mandatória**: **Todas as novas funcionalidades adicionadas à ferramenta serão implementadas exclusivamente como Plugins** dentro da pasta `app/plugins/`.

---

### 28.2 Especificação da Arquitetura de Plugins

Todas as novas funções serão empacotadas no seguinte padrão plug-and-play:

#### Estrutura de Pastas de um Plugin (`app/plugins/<id_plugin>/`):
- `plugin.json` — Manifesto com metadados (id, name, version, sector, description, dependencies).
- `plugin.py` — Classe principal herdando de `BasePlugin`.
- `routes.py` — Blueprint isolado do plugin.
- `models.py` — Modelos de dados exclusivos da extensão.
- `templates/` — Visualizações Jinja específicas.

#### Contrato de Código (`BasePlugin`):
```python
from app.core.plugins import BasePlugin

class MeuNovoPlugin(BasePlugin):
    id = "meu_novo_plugin"
    name = "Nova Funcionalidade"
    sector = "gestao_clientes"
    version = "1.0.0"

    def on_enable(self, app):
        """Registra rotas, listeners de evento e injeta elementos na UI."""
        pass

    def on_disable(self, app):
        """Remove hooks e suspende execuções do plugin."""
        pass

    def register_hooks(self, event_bus):
        """Escuta eventos do sistema (ex: ao criar lead, ao receber mensagem)."""
        event_bus.subscribe("client.created", self.on_client_created)

    def on_client_created(self, client):
        # Lógica personalizada da nova função
        pass
```

---

### 28.3 Plano de Execução Faseada da Refatoração

```mermaid
gantt
    title Cronograma de Refatoração Faseada e Sistema de Plugins
    dateFormat  YYYY-MM-DD
    section Fase 1
    Estrutura por Setores & ModuleRegistry   :active, f1, 2026-10-01, 3d
    section Fase 2
    Motor Core de Plugins & EventBus        :f2, after f1, 2d
    section Fase 3
    Desacoplamento Fino & Feature Flags     :f3, after f2, 2d
    section Fase 4
    Migração de Novas Funções & Homologação :f4, after f3, 1d
```

| Fase | Objetivo | Entregáveis Principais | Risco |
|:---:|:---|:---|:---:|
| **Fase 1** | **Reorganização em Setores** | Reestruturar código em `app/sectors/`, separar models e criar `ModuleRegistry`. | 🟢 Baixo |
| **Fase 2** | **Motor de Plugins** | Implementar `BasePlugin`, `EventBus`, `PluginRegistry` e painel visual `/admin/plugins`. | 🟢 Baixo |
| **Fase 3** | **Guards & Feature Flags** | Proteger rotas com `@requires_module`, tornar UI dinâmica e isolar workers Celery/Redis. | 🟡 Médio |
| **Fase 4** | **Validação & Plugins-First** | Transformar novas funções em plugins, testar ligar/desligar em runtime e homologar suíte. | 🟢 Baixo |

---

> *Documento atualizado com manual completo de desenvolvimento, servidores dedicados, Coolify, Ollama IA Local, Sistema Anti-Ban / Anti-Spam WhatsApp, Prospecção Ativa Google Maps, Resposta Automática Inteligente com Debounce, Painel Gráfico em Tempo Real, Nova Interface de Configuração do Bot, Central de Backup Completo, Captura Ativa de Mensagens do WhatsApp, Enriquecimento Progressivo de Leads, Sistema de Busca Inteligente com Filtros, Novo Padrão de Cards Proporcionais no Funil Kanban, Layout Otimizado na Prospecção Ativa, Padronização Visual Global, Procedimento de Recuperação WAHA, Painel Avançado de Calibração e Treinamento RAG, Plano de Modularização e Feature Flags, Correção/Normalização de Telefones WhatsApp, Aprendizado Contínuo com Conversas & RAG Estrito, Ingestão Semântica de Websites, Skills & Diretrizes de Atendimento, Central de Integrações Desacopladas com Módulo ERP Bling, Guia do Desenvolvedor para Novas Integrações e Plano Diretor de Refatoração Faseada por Setores & Arquitetura de Plugins Desligáveis.*









