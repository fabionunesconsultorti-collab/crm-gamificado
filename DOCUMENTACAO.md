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
- **Comunicação Web API (Requisições HTTP)**: A biblioteca `requests` do Python possibilita o despache instantâneo de mensagens pelo servidor diretamente para modems/APIs como o Evolution API.

## 3. Estrutura de Diretórios e Blueprints
A aplicação usa a estrutura em **Blueprints** para facilitar a escalabilidade de módulos separados:

- `app/` *(Centro Espinhal)*
  - `__init__.py`: (Fábrica da Aplicação) Inicializa o app, junta as extensões do Flask e configura URL e chaves secretas.
  - `models.py`: Toda a estrutura (schemas) das tabelas que vão pro banco de dados (Usuários, Clientes, Lojas, Configurações e Histórico de Logs). 
  - `main/`: Módulo e rotas para Landing Page / Dashboard, incluindo o modelo da Tela de Ranking.
  - `auth/`: Módulo independente gerindo Autenticações (login, logout, session data e senhas seguras por hash).
  - `admin/`: Módulo e telas administrativas, acessíveis apenas para *admind/gerentes*. Focado em adicionar/remover Lojas, visualizar todos os Logs, inserir templates novos e administrar permissionamento e configuração do motor Evolution.
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
4. **Acoplador de API (`utils/waha.py`)**: Arquivo Python que mapeia a documentação oficial da WAHA API. Ele pesquisa na tabela global as definições em tempo real da URL do seu servidor (`evo_api_url`), Chave (`evo_api_key`) e a Sessão ativa (`evo_instance`).

## 5. Mapeamento Relevante das Variáveis do Banco de Dados
A tabela **Client** possui um escopo estendido para varejo moderno:
- **`public_id`** (UUIDv4): Criado para integração robusta com outros sistemas via API, para não expor a contagem de Identificação do Banco Central (Nº ID).
- **`cpf`**: Não obrigatório, porém atrelado a integridade Única se acionado (Única String).
- **`phone`**: Celular com verificação única, crucial para disparo unificado sem contatar a mesma pessoa com ruídos idênticos.
- **Parâmetros Estratégicos**: `tier` (nível: bronze, ouro, vip), `loyalty_points` (pontuação baseada na frequência e engajamento), `badges` (tags de segmentação CSV customizáveis) e LGPD (`opt_in`, permitindo auditoria local para envio em conformidade com as regras brasileiras).

---

## 6. Configuração do Servidor WAHA (Instância Remota)
Para rodar o WAHA (WhatsApp HTTP API) em um ambiente remoto (ex: Windows com Docker), siga o procedimento de instalação profissional com persistência e cache:

### 1. Pré-requisitos
- **Docker Desktop**: Instalado e com WSL2 habilitado.
- **Terminal**: PowerShell ou CMD.

### 2. Configuração do Ambiente
Crie uma pasta (ex: `C:\waha-api`) e salve o seguinte arquivo `docker-compose.yml`:

```yaml
version: '3.8'

services:
  # Banco de Dados PostgreSQL para persistência de sessões e dados
  postgres:
    image: postgres:15
    restart: always
    environment:
      POSTGRES_DB: waha
      POSTGRES_USER: waha_user
      POSTGRES_PASSWORD: waha_password
    volumes:
      - ./postgres_data:/var/lib/postgresql/data

  # Redis para gerenciamento de cache e filas
  redis:
    image: redis:alpine
    restart: always
    volumes:
      - ./redis_data:/data

  # Instância principal do WAHA
  waha:
    image: devlikeapro/waha
    restart: always
    ports:
      - "3000:3000"
    environment:
      # Configurações do Banco de Dados
      - WHATSAPP_API_DATABASE_URL=postgresql://waha_user:waha_password@postgres:5432/waha
      # Configurações do Redis
      - WHATSAPP_API_REDIS_URL=redis://redis:6379
      # Ativa a persistência
      - WHATSAPP_API_SESSION_STORAGE=postgres
      # Configurações básicas
      - WHATSAPP_API_HOSTNAME=0.0.0.0
      - TZ=America/Sao_Paulo
    depends_on:
      - postgres
      - redis
```

### 3. Inicialização
No terminal dentro da pasta escolhida, execute:
```bash
docker-compose up -d
```
O serviço estará disponível em `http://localhost:3000` ou pelo IP da máquina na rede local.

---
> *Este documento foi formatado para refletir a migração para WAHA API e a centralização dos disparos no CRM. Deve ser modificado caso o banco ou stack primário evolua para ambientes Kubernetes em produções avançadas.*
