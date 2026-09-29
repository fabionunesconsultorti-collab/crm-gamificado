# 🔌 Integração ERP Bling — Guia Rápido

## 1. Configurar Aplicativo no Bling (API v3)
Acesse **Configurações -> Preferências -> Sistema -> Aplicativos e API v3** no Bling ERP:

| Campo | Preenchimento |
| :--- | :--- |
| **Descrição curta** | `Integração bi-direcional com CRM Pro para clientes e vendas.` |
| **Nome / E-mail / Celular** | Dados do responsável pelo CRM |
| **URI de Redirecionamento** | `http://localhost:5000/integrations/bling/callback` *(ou URL de Produção)* |
| **Escopos Permitidos** | ✅ **Contatos** *(Leitura/Escrita)* \| ✅ **Pedidos de Vendas** *(Leitura)* \| ✅ **Situações** *(Leitura)* |

### 1.1. Configurar Webhooks no Bling ERP
Na aba **Webhooks** do aplicativo no Bling:
- **URL do Servidor**: `http://localhost:5000/integrations/bling/webhook` *(ou `https://seu-dominio.com.br/integrations/bling/webhook`)*
- **Versão**: `v1` (ou `v3`)
- **Ações Notificadas**:
  - **Estoques**: ✅ Criação \| ✅ Atualização \| ✅ Exclusão
  - **Produtos**: ✅ Criação \| ✅ Atualização \| ✅ Exclusão
  - **Pedidos de Vendas**: ✅ Criação \| ✅ Atualização \| ✅ Exclusão *(Atualiza faturamento no CRM)*
  - **Fornecedores / Contatos**: ✅ Criação \| ✅ Atualização \| ✅ Exclusão *(Cria/atualiza cliente no CRM)*


---

## 2. Ativar no CRM (`/integrations/admin`)
1. Acesse **Administração -> Central Integrações**.
2. Clique em **Configurar** no card do Bling e insira o `Client ID`, `Client Secret` e `Access Token`.
3. Clique em **Testar Conexão** e alterne a chave para **LIGADO (ON)**.

---

## 3. Principais Operações & Relatórios
- **Puxar / Subir Clientes**: Sincronização bi-direcional de contatos com deduplicação.
- **Bling Analytics (`/integrations/bling/dashboard`)**: KPIs de Faturamento, Ticket Médio, Curva ABC Top 10 e exportação CSV.
- **Relatórios para Tomada de Decisão (`/integrations/bling/reports`)**:
  - 📦 **Estoque Parado**: Análise de capital travado por Marca, Fornecedor, Categoria e Dias sem Venda (30d, 60d, 90d+).
  - 👥 **Análise de Clientes**: Últimas compras, Ticket Médio, Histórico de Faturamento e Classificação RFM (VIP, Novos, Risco de Churn).
  - 📏 **Filtro por Tamanho & Tipo**: Análise de estoque e vendas por Tamanho (P, M, G, GG, numéricos) e Tipo de Produto.
  - 📊 **Exportação CSV**: Download de qualquer um dos 3 relatórios com filtros aplicados.


---

## 4. Como Adicionar Novas Integrações (Devs)
1. Crie a pasta `app/integrations/<provedor>/` e o arquivo `adapter.py`.
2. Herde de `BaseIntegrationAdapter` e use a anotação `@IntegrationManager.register`:

```python
from app.integrations.base import BaseIntegrationAdapter
from app.integrations.manager import IntegrationManager

@IntegrationManager.register
class NovoAdapter(BaseIntegrationAdapter):
    provider_name = "novo_provedor"
    display_name = "Nome Exibição"
    description = "Descrição curta da integração."

    def test_connection(self) -> dict: return {"success": True, "message": "OK"}
    def sync_clients_inbound(self, limit: int = 100) -> dict: return {"success": True, "message": "OK"}
    def sync_clients_outbound(self, client_id=None) -> dict: return {"success": True, "message": "OK"}
    def fetch_sales_reports(self, start_date=None, end_date=None) -> dict: return {"success": True, "message": "OK"}
```

3. Importe a classe no arquivo `app/integrations/__init__.py`.
*(A tela `/integrations/admin` cria o Card ON/OFF e Modal automaticamente).*

---

## 5. Testes Automatizados
```bash
venv/bin/python3 -m unittest tests/test_bling_integration.py
```
