import csv
import io
from flask import render_template, request, jsonify, flash, redirect, url_for, Response
from flask_login import login_required, current_user
from app import db
from app.models import Client, ExternalEntityMap, IntegrationLog, BlingProductCache, BlingSalesCache
from app.integrations import bp
from app.integrations.manager import IntegrationManager
from app.integrations.bling.adapter import BlingAdapter

@bp.route('/admin', methods=['GET'])
@login_required
def admin_integrations():
    """Página principal da Central de Integrações — Hub Limpo e Modular."""
    if current_user.role not in ['admin', 'gerente']:
        flash('Acesso negado.')
        return redirect(url_for('main.index'))

    from app.core.module_registry import is_module_enabled
    adapter = IntegrationManager.get_adapter('bling')
    is_bling_active = adapter.is_enabled() if adapter else False

    # Catálogo de Integrações Disponíveis no Sistema
    hub_integrations = [
        {
            'id': 'waha_bulk',
            'name': 'Disparo em Lote WAHA',
            'description': 'Motor desacoplado de disparos massivos, campanhas em segundo plano, termômetro de risco e proteção anti-ban.',
            'icon': 'fa-solid fa-rocket',
            'icon_color': '#25D366',
            'icon_bg': 'rgba(37, 211, 102, 0.15)',
            'badge': 'Anti-Ban Ativo',
            'category': 'Mensageria',
            'is_active': is_module_enabled('waha_bulk'),
            'tool_url': url_for('crm.bulk_message'),
            'tool_label': 'Abrir Painel de Disparo'
        },
        {
            'id': 'waha',
            'name': 'WhatsApp WAHA Gateway',
            'description': 'Gateway HTTP oficial para WhatsApp. Gerenciamento de instâncias, sessões conectadas e recepção de mensagens.',
            'icon': 'fa-brands fa-whatsapp',
            'icon_color': '#10b981',
            'icon_bg': 'rgba(16, 185, 129, 0.15)',
            'badge': 'API Oficial',
            'category': 'Mensageria',
            'is_active': is_module_enabled('waha'),
            'tool_url': url_for('admin.settings') + '?tab=waha',
            'tool_label': 'Gerenciar Instâncias'
        },
        {
            'id': 'bling',
            'name': 'Bling ERP',
            'description': 'Sincronização bidirecional de produtos, catálogo de estoque, contatos e pedidos de venda com o Bling.',
            'icon': 'fa-solid fa-boxes-packing',
            'icon_color': '#f59e0b',
            'icon_bg': 'rgba(245, 158, 11, 0.15)',
            'badge': 'ERP & Estoque',
            'category': 'ERP & Vendas',
            'is_active': is_bling_active,
            'tool_url': url_for('integrations.bling_tools'),
            'tool_label': 'Abrir Ferramentas Bling'
        },
        {
            'id': 'prospecting',
            'name': 'Prospecção Google Maps',
            'description': 'Scraper automatizado de leads qualificados, telefones comerciais e dados de empresas pelo Google Maps.',
            'icon': 'fa-solid fa-map-location-dot',
            'icon_color': '#3b82f6',
            'icon_bg': 'rgba(59, 130, 246, 0.15)',
            'badge': 'Lead Scraper',
            'category': 'Aquisição de Leads',
            'is_active': is_module_enabled('prospecting'),
            'tool_url': url_for('crm.prospeccao'),
            'tool_label': 'Abrir Prospecção Maps'
        },
        {
            'id': 'ia_automacao',
            'name': 'Inteligência Artificial (Ollama / LLMs)',
            'description': 'Modelos locais neurais para atendimento automático, humanização anti-spam de mensagens e base RAG.',
            'icon': 'fa-solid fa-robot',
            'icon_color': '#8b5cf6',
            'icon_bg': 'rgba(139, 92, 246, 0.15)',
            'badge': 'Llama 3.2 / Ollama',
            'category': 'Inteligência Artificial',
            'is_active': is_module_enabled('auto_responder'),
            'tool_url': url_for('admin.settings') + '?tab=ia',
            'tool_label': 'Configurar Modelos IA'
        },
        {
            'id': 'webhooks',
            'name': 'Webhooks & APIs Externas',
            'description': 'Recepção e disparo de eventos JSON em tempo real para automações externas (n8n, Typebot, Make).',
            'icon': 'fa-solid fa-network-wired',
            'icon_color': '#ec4899',
            'icon_bg': 'rgba(236, 72, 153, 0.15)',
            'badge': 'Automação',
            'category': 'Webhooks',
            'is_active': is_module_enabled('webhooks'),
            'tool_url': url_for('admin.settings') + '?tab=webhooks',
            'tool_label': 'Configurar Webhooks'
        }
    ]

    logs = IntegrationLog.query.order_by(IntegrationLog.timestamp.desc()).limit(20).all()

    return render_template(
        'admin/integrations.html',
        title='Central de Integrações',
        integrations=hub_integrations,
        logs=logs
    )


@bp.route('/bling/tools', methods=['GET'])
@login_required
def bling_tools():
    """Tela distinta e dedicada para as ferramentas e sincronizações do Bling ERP."""
    if current_user.role not in ['admin', 'gerente']:
        flash('Acesso negado.')
        return redirect(url_for('main.index'))

    adapter = IntegrationManager.get_adapter('bling')
    is_bling_active = adapter.is_enabled() if adapter else False
    config = adapter.get_config() if adapter else None

    if is_bling_active:
        products_count = BlingProductCache.query.count()
        sales_count = BlingSalesCache.query.count()
        clients_count = ExternalEntityMap.query.filter_by(provider='bling', crm_entity_type='client').count()

        brands_count = db.session.query(db.func.count(db.func.distinct(BlingProductCache.brand))).scalar() or 0
        categories_count = db.session.query(db.func.count(db.func.distinct(BlingProductCache.category))).scalar() or 0
        sizes_count = db.session.query(db.func.count(db.func.distinct(BlingProductCache.size))).scalar() or 0
        suppliers_count = db.session.query(db.func.count(db.func.distinct(BlingProductCache.supplier_name))).scalar() or 0

        brands_list = [b[0] for b in db.session.query(BlingProductCache.brand).distinct().all() if b[0]]
        categories_list = [c[0] for c in db.session.query(BlingProductCache.category).distinct().all() if c[0]]
        sizes_list = [s[0] for s in db.session.query(BlingProductCache.size).distinct().all() if s[0]]
    else:
        products_count = 0
        sales_count = 0
        clients_count = 0
        brands_count = 0
        categories_count = 0
        sizes_count = 0
        suppliers_count = 0
        brands_list = []
        categories_list = []
        sizes_list = []

    total_local = products_count + clients_count + sales_count
    remote_totals = {"total_products": products_count, "total_contacts": clients_count, "total_sales": sales_count}

    summary_stats = {
        'products_count': products_count,
        'sales_count': sales_count,
        'clients_count': clients_count,
        'brands_count': brands_count,
        'categories_count': categories_count,
        'sizes_count': sizes_count,
        'suppliers_count': suppliers_count,
        'brands_list': sorted(brands_list),
        'categories_list': sorted(categories_list),
        'sizes_list': sorted(sizes_list),
        'remote_totals': remote_totals,
        'total_remote': total_local,
        'total_local': total_local,
        'remaining': 0,
        'progress_pct': 100 if is_bling_active else 0
    }

    return render_template(
        'crm/bling_tools.html',
        title='Ferramentas Bling ERP',
        summary=summary_stats,
        config=config,
        is_active=is_bling_active
    )


@bp.route('/api/hub/toggle', methods=['POST'])
@login_required
def api_hub_toggle():
    """Ativa ou desativa qualquer integração do Hub com segurança e sem prejuízo."""
    if current_user.role not in ['admin', 'gerente']:
        return jsonify({'success': False, 'message': 'Acesso negado'}), 403

    from app.models import Setting
    data = request.get_json(silent=True) or request.form or {}
    provider = data.get('provider')
    enable = str(data.get('enable', 'true')).lower() in ['true', '1', 'yes']

    if not provider:
        return jsonify({'success': False, 'message': 'Identificador da integração não informado.'}), 400

    if provider == 'waha_bulk':
        Setting.set_val('module_integracoes_waha_bulk_enabled', 'true' if enable else 'false')
        if not enable:
            from app.tasks.bulk_engine import freeze_engine_gracefully
            freeze_engine_gracefully("Módulo desativado na Central de Integrações")
        db.session.commit()
        return jsonify({'success': True, 'enabled': enable, 'message': f"Disparo em Lote WAHA {'ativado' if enable else 'desativado com segurança'}!"})

    elif provider == 'waha':
        Setting.set_val('module_integracoes_waha_enabled', 'true' if enable else 'false')
        db.session.commit()
        return jsonify({'success': True, 'enabled': enable, 'message': f"Gateway WAHA {'ativado' if enable else 'desativado'}!"})

    elif provider == 'bling':
        result = IntegrationManager.toggle_integration('bling', enable)
        return jsonify({'success': result.get('success', False), 'enabled': enable, 'message': result.get('message')})

    elif provider == 'prospecting':
        Setting.set_val('module_gestao_clientes_prospecting_enabled', 'true' if enable else 'false')
        db.session.commit()
        return jsonify({'success': True, 'enabled': enable, 'message': f"Prospecção Google Maps {'ativada' if enable else 'desativada'}!"})

    elif provider == 'ia_automacao':
        Setting.set_val('module_ia_automacao_auto_responder_enabled', 'true' if enable else 'false')
        db.session.commit()
        return jsonify({'success': True, 'enabled': enable, 'message': f"Modelos de IA {'ativados' if enable else 'desativados'}!"})

    elif provider == 'webhooks':
        Setting.set_val('module_integracoes_webhooks_enabled', 'true' if enable else 'false')
        db.session.commit()
        return jsonify({'success': True, 'enabled': enable, 'message': f"Webhooks {'ativados' if enable else 'desativados'}!"})

    return jsonify({'success': False, 'message': 'Provedor não reconhecido.'}), 400



@bp.route('/bling/status-summary', methods=['GET'])
@login_required
def bling_status_summary():
    """Retorna o status detalhado da sincronização com o Bling ERP em tempo real para o gráfico de progresso."""
    adapter = IntegrationManager.get_adapter('bling')
    if not adapter or not adapter.is_enabled():
        return jsonify({'active': False})

    products_count = BlingProductCache.query.count()
    sales_count = BlingSalesCache.query.count()
    clients_count = Client.query.count()

    brands_count = db.session.query(db.func.count(db.func.distinct(BlingProductCache.brand))).scalar() or 0
    categories_count = db.session.query(db.func.count(db.func.distinct(BlingProductCache.category))).scalar() or 0
    sizes_count = db.session.query(db.func.count(db.func.distinct(BlingProductCache.size))).scalar() or 0
    suppliers_count = db.session.query(db.func.count(db.func.distinct(BlingProductCache.supplier_name))).scalar() or 0

    remote_totals = adapter.get_remote_totals()

    total_remote = (remote_totals.get('total_products') or 0) + (remote_totals.get('total_contacts') or 0) + (remote_totals.get('total_sales') or 0)
    total_local = products_count + clients_count + sales_count

    progress_pct = 100 if (total_remote == 0 or total_local >= total_remote) else round((total_local / total_remote) * 100)
    remaining = max(0, total_remote - total_local)

    return jsonify({
        'active': True,
        'products_count': products_count,
        'sales_count': sales_count,
        'clients_count': clients_count,
        'brands_count': brands_count,
        'categories_count': categories_count,
        'sizes_count': sizes_count,
        'suppliers_count': suppliers_count,
        'remote_totals': remote_totals,
        'total_remote': total_remote,
        'total_local': total_local,
        'remaining': remaining,
        'progress_pct': progress_pct
    })


@bp.route('/bling/sync-all', methods=['POST'])
@login_required
def sync_all_bling():
    """Executa a sincronização completa de Clientes, Vendas, Produtos e Estoque do Bling ERP em 1 clique."""
    if current_user.role not in ['admin', 'gerente']:
        return jsonify({'success': False, 'message': 'Acesso negado.'}), 403

    adapter = IntegrationManager.get_adapter('bling')
    if not adapter or not adapter.is_enabled():
        return jsonify({'success': False, 'message': 'Integração com o Bling está desativada.'}), 400

    res_clients = adapter.fetch_and_sync_clients(limit=None)
    res_sales = adapter.fetch_sales_orders(limit=None)
    res_products = adapter.fetch_products_and_stock(limit=None)

    msg = f"Sincronização Geral Concluída! {res_clients.get('message', '')} | {res_sales.get('message', '')} | {res_products.get('message', '')}"
    adapter.log('sync_all', 'success', msg)

    return jsonify({
        'success': True,
        'message': msg,
        'clients': res_clients,
        'sales': res_sales,
        'products': res_products
    })

@bp.route('/<provider>/toggle', methods=['POST'])
@login_required
def toggle_integration(provider):
    """Ativa ou desativa um integrador (Feature Flag)."""
    if current_user.role not in ['admin', 'gerente']:
        return jsonify({'success': False, 'message': 'Acesso negado.'}), 403

    data = request.get_json() or {}
    active = data.get('active', False)
    res = IntegrationManager.toggle_integration(provider, active)
    return jsonify(res)

@bp.route('/<provider>/config', methods=['POST'])
@login_required
def update_config(provider):
    """Atualiza as credenciais de um integrador."""
    if current_user.role not in ['admin', 'gerente']:
        return jsonify({'success': False, 'message': 'Acesso negado.'}), 403

    data = request.get_json() or request.form.to_dict()
    res = IntegrationManager.update_config(provider, data)
    return jsonify(res)

@bp.route('/<provider>/test', methods=['POST'])
@login_required
def test_connection(provider):
    """Testa a conexão com o servidor externo do integrador."""
    if current_user.role not in ['admin', 'gerente']:
        return jsonify({'success': False, 'message': 'Acesso negado.'}), 403

    adapter = IntegrationManager.get_adapter(provider)
    if not adapter:
        return jsonify({'success': False, 'message': f'Provedor {provider} não encontrado.'}), 4404

    res = adapter.test_connection()
    return jsonify(res)

@bp.route('/<provider>/sync-clients', methods=['POST'])
@login_required
def sync_clients(provider):
    """Executa a sincronização de clientes (inbound ou outbound)."""
    if current_user.role not in ['admin', 'gerente']:
        return jsonify({'success': False, 'message': 'Acesso negado.'}), 403

    data = request.get_json() or {}
    direction = data.get('direction', 'inbound')
    limit = data.get('limit', None)

    adapter = IntegrationManager.get_adapter(provider)
    if not adapter:
        return jsonify({'success': False, 'message': f'Provedor {provider} não encontrado.'}), 404

    if not adapter.is_enabled():
        return jsonify({'success': False, 'message': f'A integração {adapter.display_name} está desativada.'}), 400

    if direction == 'inbound':
        res = adapter.sync_clients_inbound(limit=limit)
    else:
        res = adapter.sync_clients_outbound()

    return jsonify(res)

@bp.route('/<provider>/sync-sales', methods=['POST'])
@login_required
def sync_sales(provider):
    """Busca vendas do ERP e atualiza o cache local."""
    if current_user.role not in ['admin', 'gerente']:
        return jsonify({'success': False, 'message': 'Acesso negado.'}), 403

    adapter = IntegrationManager.get_adapter(provider)
    if not adapter:
        return jsonify({'success': False, 'message': f'Provedor {provider} não encontrado.'}), 404

    if not adapter.is_enabled():
        return jsonify({'success': False, 'message': f'A integração {adapter.display_name} está desativada.'}), 400

    res = adapter.fetch_sales_reports()
    return jsonify(res)

@bp.route('/bling/dashboard', methods=['GET'])
@login_required
def bling_dashboard():
    """Dashboard de Analytics e Relatórios do Bling ERP."""
    adapter = IntegrationManager.get_adapter('bling')
    if not adapter:
        flash('Módulo do Bling ERP não registrado.')
        return redirect(url_for('main.index'))

    if not adapter.is_enabled():
        flash('A integração com o Bling ERP está inativa. Ative-a na Central de Integrações para visualizar os relatórios.')
        return redirect(url_for('integrations.admin_integrations'))

    is_active = True
    metrics = adapter.get_dashboard_metrics()

    return render_template(
        'crm/bling_dashboard.html',
        title='Bling ERP — Analytics & Relatórios',
        is_active=is_active,
        metrics=metrics
    )

@bp.route('/bling/export', methods=['GET'])
@login_required
def export_bling_sales():
    """Exporta o relatório de vendas do Bling em formato CSV."""
    adapter = IntegrationManager.get_adapter('bling')
    if not adapter or not adapter.is_enabled():
        flash('Integração com o Bling ERP está desativada.')
        return redirect(url_for('main.index'))

    metrics = adapter.get_dashboard_metrics()
    recent_sales = metrics.get('recent_sales', [])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID Bling', 'Número Pedido', 'CPF/CNPJ', 'Cliente', 'Valor Total (R$)', 'Data Venda', 'Status', 'Vendedor'])

    for s in recent_sales:
        writer.writerow([
            s.get('bling_order_id', ''),
            s.get('order_number', ''),
            s.get('client_cpf_cnpj', ''),
            s.get('client_name', ''),
            s.get('total_value', 0.0),
            s.get('order_date', ''),
            s.get('status', ''),
            s.get('seller_name', '')
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={"Content-Disposition": "attachment;filename=relatorio_vendas_bling.csv"}
    )

@bp.route('/bling/sync-client/<int:client_id>', methods=['POST'])
@login_required
def sync_single_client(client_id):
    """Envia um cliente específico do CRM para o Bling ERP."""
    adapter = IntegrationManager.get_adapter('bling')
    if not adapter or not adapter.is_enabled():
        return jsonify({'success': False, 'message': 'Integração com o Bling está desativada.'}), 400

    client = Client.query.get_or_404(client_id)
    res = adapter.sync_clients_outbound(client_id=client.id)
    return jsonify(res)

@bp.route('/bling/callback', methods=['GET'])
@login_required
def bling_oauth_callback():
    """Endpoint Callback da URI de Redirecionamento do aplicativo Bling OAuth 2.0."""
    code = request.args.get('code')
    error = request.args.get('error')

    if error:
        flash(f'Erro na autorização do Bling ERP: {error}')
        return redirect(url_for('integrations.admin_integrations'))

    if code:
        adapter = IntegrationManager.get_adapter('bling')
        if adapter:
            config = adapter.get_config()
            if config.client_id and config.client_secret:
                try:
                    import requests
                    token_url = "https://api.bling.com.br/v3/oauth/token"
                    payload = {
                        "grant_type": "authorization_code",
                        "code": code
                    }
                    auth_header = requests.auth.HTTPBasicAuth(config.client_id, config.client_secret)
                    resp = requests.post(token_url, data=payload, auth=auth_header, timeout=10)
                    if resp.status_code in [200, 201]:
                        token_data = resp.json()
                        config.access_token = token_data.get('access_token')
                        config.refresh_token = token_data.get('refresh_token')
                        config.is_active = True
                        db.session.commit()
                        flash('Autenticação OAuth2 do Bling ERP realizada com sucesso!')
                        adapter.log('oauth_callback', 'success', 'Access token obtido com sucesso via OAuth2.')
                    else:
                        flash(f'Código OAuth2 recebido ({code[:10]}...), mas resposta do token: {resp.text[:150]}')
                        adapter.log('oauth_callback', 'warning', f'Code recebido. Token response status={resp.status_code}')
                except Exception as ex:
                    flash(f'Código OAuth2 recebido: {code[:10]}... (Verifique os logs)')
                    adapter.log('oauth_callback', 'info', f'Code recebido via callback: {code}')
            else:
                config.access_token = code
                db.session.commit()
                flash('Código OAuth2 recebido com sucesso!')

    return redirect(url_for('integrations.admin_integrations'))

@bp.route('/bling/webhook', methods=['POST'])
def bling_webhook_receiver():
    """Endpoint público de recepção de Webhooks do Bling ERP (Clientes, Pedidos, Estoque, Produtos)."""
    adapter = IntegrationManager.get_adapter('bling')
    if not adapter or not adapter.is_enabled():
        return jsonify({'success': False, 'message': 'Integração Bling inativa.'}), 200

    try:
        data = request.get_json(silent=True) or request.form.to_dict() or {}
        res = adapter.process_webhook_event(data)
        return jsonify(res), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 200

@bp.route('/bling/reports', methods=['GET'])
@login_required
def bling_reports():
    """Painel de Relatórios Estratégicos e Tomada de Decisão (Estoque Parado, Análise de Clientes e Filtro por Tamanho/Tipo)."""
    adapter = IntegrationManager.get_adapter('bling')
    if not adapter:
        flash('Módulo do Bling ERP não registrado.')
        return redirect(url_for('main.index'))

    if not adapter.is_enabled():
        flash('A integração com o Bling ERP está inativa. Ative-a na Central de Integrações para acessar a tela de tomada de decisão.')
        return redirect(url_for('integrations.admin_integrations'))

    is_active = True
    
    # Captura filtros da query string
    filters = {
        'brand': request.args.get('brand', 'all'),
        'supplier': request.args.get('supplier', 'all'),
        'category': request.args.get('category', 'all'),
        'min_days': request.args.get('min_days', '0'),
        'rfm_status': request.args.get('rfm_status', 'all'),
        'size': request.args.get('size', 'all'),
        'active_tab': request.args.get('tab', 'stock')
    }


    report_data = adapter.get_decision_reports_data(filters) if is_active else {}

    return render_template(
        'crm/bling_reports.html',
        title='Relatórios para Tomada de Decisão — Bling',
        is_active=is_active,
        filters=filters,
        data=report_data
    )

@bp.route('/bling/sync-products', methods=['POST'])
@login_required
def sync_products():
    """Busca a lista de produtos e estoque do Bling ERP e atualiza o cache local."""
    if current_user.role not in ['admin', 'gerente']:
        return jsonify({'success': False, 'message': 'Acesso negado.'}), 403

    adapter = IntegrationManager.get_adapter('bling')
    if not adapter or not adapter.is_enabled():
        return jsonify({'success': False, 'message': 'Integração com o Bling está desativada.'}), 400

    res = adapter.fetch_products_and_stock()
    return jsonify(res)

@bp.route('/bling/reports/export', methods=['GET'])
@login_required
def export_bling_reports():
    """Exporta o relatório selecionado (Estoque Parado, Clientes, Tamanho/Tipo) em CSV."""
    adapter = IntegrationManager.get_adapter('bling')
    if not adapter or not adapter.is_enabled():
        flash('Integração com o Bling ERP está desativada.')
        return redirect(url_for('main.index'))

    report_type = request.args.get('type', 'stock')
    filters = {
        'brand': request.args.get('brand', 'all'),
        'supplier': request.args.get('supplier', 'all'),
        'category': request.args.get('category', 'all'),
        'min_days': request.args.get('min_days', '0'),
        'rfm_status': request.args.get('rfm_status', 'all'),
        'size': request.args.get('size', 'all')
    }

    report_data = adapter.get_decision_reports_data(filters)
    output = io.StringIO()
    writer = csv.writer(output)

    if report_type == 'stock':
        writer.writerow(['SKU/Código', 'Produto', 'Marca', 'Fornecedor', 'Categoria', 'Tamanho', 'Estoque Atual', 'Preço Custo (R$)', 'Preço Venda (R$)', 'Capital Parado (R$)', 'Dias Sem Venda'])
        for p in report_data.get('stock_report', []):
            writer.writerow([
                p.get('code', ''), p.get('name', ''), p.get('brand', ''),
                p.get('supplier_name', ''), p.get('category', ''), p.get('size', ''),
                p.get('current_stock', 0), p.get('cost_price', 0.0), p.get('price', 0.0),
                p.get('capital_locked', 0.0), p.get('days_without_sale', 0)
            ])
        filename = "relatorio_estoque_parado.csv"

    elif report_type == 'clients':
        writer.writerow(['Cliente', 'CPF/CNPJ', 'Total Comprado (R$)', 'Qtd Pedidos', 'Ticket Médio (R$)', 'Última Compra', 'Dias Sem Comprar', 'Classificação RFM'])
        for c in report_data.get('clients_report', []):
            writer.writerow([
                c.get('client_name', ''), c.get('cpf_cnpj', ''),
                c.get('total_spent', 0.0), c.get('total_orders', 0),
                c.get('ticket_medio', 0.0), c.get('last_purchase_str', ''),
                c.get('days_since_last', 0), c.get('status_rfm', '')
            ])
        filename = "relatorio_analise_clientes.csv"

    else:
        writer.writerow(['--- RESUMO POR CATEGORIA E TAMANHO ---'])
        writer.writerow(['Categoria/Tipo', 'Tamanho', 'Total em Estoque', 'Qtd de Produtos', 'Valor em Estoque (R$)'])
        for s in report_data.get('size_report', []):
            writer.writerow([
                s.get('category', ''), s.get('size', ''),
                s.get('total_stock', 0), s.get('products_count', 0),
                s.get('total_value', 0.0)
            ])
        writer.writerow([])
        writer.writerow(['--- LISTAGEM COMPLETA DOS PRODUTOS FILTRADOS ---'])
        writer.writerow(['SKU/Código', 'Produto', 'Marca', 'Fornecedor', 'Categoria', 'Tamanho', 'Estoque Atual', 'Preço Custo (R$)', 'Preço Venda (R$)', 'Valor Total Estoque (R$)', 'Dias Sem Venda'])
        for p in report_data.get('size_products_report', []):
            writer.writerow([
                p.get('code', ''), p.get('name', ''), p.get('brand', ''),
                p.get('supplier_name', ''), p.get('category', ''), p.get('size', ''),
                p.get('current_stock', 0), p.get('cost_price', 0.0), p.get('price', 0.0),
                p.get('capital_locked', 0.0), p.get('days_without_sale', 0)
            ])
        filename = "relatorio_produtos_por_tamanho.csv"

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )


@bp.route('/bling/reports/export-pdf', methods=['GET'])
@login_required
def export_bling_reports_pdf():
    """Exporta o relatório selecionado (Estoque Parado, Clientes, Tamanho/Tipo) em formato PDF."""
    adapter = IntegrationManager.get_adapter('bling')
    if not adapter or not adapter.is_enabled():
        flash('Integração com o Bling ERP está desativada.')
        return redirect(url_for('main.index'))

    report_type = request.args.get('type', 'stock')
    filters = {
        'brand': request.args.get('brand', 'all'),
        'supplier': request.args.get('supplier', 'all'),
        'category': request.args.get('category', 'all'),
        'min_days': request.args.get('min_days', '0'),
        'rfm_status': request.args.get('rfm_status', 'all'),
        'size': request.args.get('size', 'all')
    }

    report_data = adapter.get_decision_reports_data(filters)

    def clean_str(s):
        return str(s or '').encode('latin-1', 'replace').decode('latin-1')

    from fpdf import FPDF
    from datetime import datetime

    class PDFReport(FPDF):
        def __init__(self, title_text):
            super().__init__(orientation='L', unit='mm', format='A4')
            self.title_text = title_text

        def header(self):
            self.set_font('Helvetica', 'B', 14)
            self.set_text_color(30, 41, 59)
            self.cell(0, 8, clean_str(self.title_text), border=0, new_x="LMARGIN", new_y="NEXT", align='C')
            self.set_font('Helvetica', 'I', 9)
            self.set_text_color(100, 116, 139)
            now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
            self.cell(0, 5, clean_str(f'CRM Pro - Relatórios Bling ERP | Gerado em: {now_str}'), border=0, new_x="LMARGIN", new_y="NEXT", align='C')
            self.ln(3)

        def footer(self):
            self.set_y(-15)
            self.set_font('Helvetica', 'I', 8)
            self.set_text_color(148, 163, 184)
            self.cell(0, 10, clean_str(f'Página {self.page_no()}/{{nb}}'), align='C')

    if report_type == 'stock':
        pdf = PDFReport('Relatório de Estoque Parado & Tomada de Decisão')
        pdf.alias_nb_pages()
        pdf.add_page()

        pdf.set_font('Helvetica', 'B', 10)
        pdf.set_fill_color(241, 245, 249)
        cap = report_data.get('total_capital_parado', 0.0)
        pecas = report_data.get('total_pecas_paradas', 0)
        items_cnt = len(report_data.get('stock_report', []))

        summary_line = f"Capital Parado: R$ {cap:,.2f}  |  Peças em Estoque Parado: {pecas} un  |  Total de Produtos Listados: {items_cnt}"
        pdf.cell(0, 8, clean_str(summary_line), border=1, fill=True, new_x="LMARGIN", new_y="NEXT", align='C')
        pdf.ln(4)

        pdf.set_font('Helvetica', 'B', 9)
        pdf.set_fill_color(30, 41, 59)
        pdf.set_text_color(255, 255, 255)

        cols = [
            ('SKU', 25), ('Produto', 65), ('Marca', 30), ('Fornecedor', 35),
            ('Categoria', 30), ('Tamanho', 20), ('Estoque', 20), ('Capital (R$)', 27), ('Dias S/Venda', 25)
        ]
        for title, width in cols:
            pdf.cell(width, 7, clean_str(title), border=1, align='C', fill=True)
        pdf.ln()

        pdf.set_font('Helvetica', '', 8)
        pdf.set_text_color(15, 23, 42)
        fill = False

        for p in report_data.get('stock_report', []):
            if pdf.get_y() > 180:
                pdf.add_page()
                pdf.set_font('Helvetica', 'B', 9)
                pdf.set_fill_color(30, 41, 59)
                pdf.set_text_color(255, 255, 255)
                for title, width in cols:
                    pdf.cell(width, 7, clean_str(title), border=1, align='C', fill=True)
                pdf.ln()
                pdf.set_font('Helvetica', '', 8)
                pdf.set_text_color(15, 23, 42)

            pdf.set_fill_color(248, 250, 252) if fill else pdf.set_fill_color(255, 255, 255)
            pdf.cell(25, 6, clean_str(p.get('code', '')[:14]), border=1, fill=fill)
            pdf.cell(65, 6, clean_str(p.get('name', '')[:35]), border=1, fill=fill)
            pdf.cell(30, 6, clean_str(p.get('brand', '')[:16]), border=1, fill=fill)
            pdf.cell(35, 6, clean_str(p.get('supplier_name', '')[:20]), border=1, fill=fill)
            pdf.cell(30, 6, clean_str(p.get('category', '')[:16]), border=1, fill=fill)
            pdf.cell(20, 6, clean_str(p.get('size', '')[:10]), border=1, align='C', fill=fill)
            pdf.cell(20, 6, clean_str(f"{p.get('current_stock', 0)} un"), border=1, align='R', fill=fill)
            pdf.cell(27, 6, clean_str(f"R$ {p.get('capital_locked', 0.0):,.2f}"), border=1, align='R', fill=fill)
            pdf.cell(25, 6, clean_str(f"{p.get('days_without_sale', 0)}d"), border=1, align='C', fill=fill)
            pdf.ln()
            fill = not fill

        filename = "relatorio_estoque_parado.pdf"

    elif report_type == 'clients':
        pdf = PDFReport('Relatório de Análise de Clientes & Compras')
        pdf.alias_nb_pages()
        pdf.add_page()

        pdf.set_font('Helvetica', 'B', 9)
        pdf.set_fill_color(30, 41, 59)
        pdf.set_text_color(255, 255, 255)

        cols = [
            ('Cliente', 60), ('CPF/CNPJ', 35), ('Total Comprado (R$)', 35),
            ('Pedidos', 22), ('Ticket Médio (R$)', 35), ('Última Compra', 30), ('Dias Inativo', 25), ('Classificação RFM', 35)
        ]
        for title, width in cols:
            pdf.cell(width, 7, clean_str(title), border=1, align='C', fill=True)
        pdf.ln()

        pdf.set_font('Helvetica', '', 8)
        pdf.set_text_color(15, 23, 42)
        fill = False

        for c in report_data.get('clients_report', []):
            if pdf.get_y() > 180:
                pdf.add_page()
                pdf.set_font('Helvetica', 'B', 9)
                pdf.set_fill_color(30, 41, 59)
                pdf.set_text_color(255, 255, 255)
                for title, width in cols:
                    pdf.cell(width, 7, clean_str(title), border=1, align='C', fill=True)
                pdf.ln()
                pdf.set_font('Helvetica', '', 8)
                pdf.set_text_color(15, 23, 42)

            pdf.set_fill_color(248, 250, 252) if fill else pdf.set_fill_color(255, 255, 255)
            pdf.cell(60, 6, clean_str(c.get('client_name', '')[:32]), border=1, fill=fill)
            pdf.cell(35, 6, clean_str(c.get('cpf_cnpj', '')[:18]), border=1, fill=fill)
            pdf.cell(35, 6, clean_str(f"R$ {c.get('total_spent', 0.0):,.2f}"), border=1, align='R', fill=fill)
            pdf.cell(22, 6, clean_str(f"{c.get('total_orders', 0)}"), border=1, align='C', fill=fill)
            pdf.cell(35, 6, clean_str(f"R$ {c.get('ticket_medio', 0.0):,.2f}"), border=1, align='R', fill=fill)
            pdf.cell(30, 6, clean_str(c.get('last_purchase_str', '')), border=1, align='C', fill=fill)
            pdf.cell(25, 6, clean_str(f"{c.get('days_since_last', 0)}d"), border=1, align='C', fill=fill)
            pdf.cell(35, 6, clean_str(c.get('status_rfm', '')), border=1, align='C', fill=fill)
            pdf.ln()
            fill = not fill

        filename = "relatorio_analise_clientes.pdf"

    else:
        pdf = PDFReport('Relatório de Produtos por Tamanho & Tipo')
        pdf.alias_nb_pages()
        pdf.add_page()

        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(0, 6, clean_str('1. Resumo Agrupado por Categoria e Tamanho'), border=0, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        pdf.set_font('Helvetica', 'B', 9)
        pdf.set_fill_color(30, 41, 59)
        pdf.set_text_color(255, 255, 255)
        cols_summary = [('Categoria / Tipo', 80), ('Tamanho', 40), ('Qtd Modelos', 40), ('Estoque Total (Peças)', 55), ('Valor Total (R$)', 60)]
        for title, width in cols_summary:
            pdf.cell(width, 7, clean_str(title), border=1, align='C', fill=True)
        pdf.ln()

        pdf.set_font('Helvetica', '', 8)
        pdf.set_text_color(15, 23, 42)
        fill = False

        for s in report_data.get('size_report', []):
            pdf.set_fill_color(248, 250, 252) if fill else pdf.set_fill_color(255, 255, 255)
            pdf.cell(80, 6, clean_str(s.get('category', '')[:40]), border=1, fill=fill)
            pdf.cell(40, 6, clean_str(s.get('size', '')[:20]), border=1, align='C', fill=fill)
            pdf.cell(40, 6, clean_str(f"{s.get('products_count', 0)} modelos"), border=1, align='C', fill=fill)
            pdf.cell(55, 6, clean_str(f"{s.get('total_stock', 0)} un"), border=1, align='R', fill=fill)
            pdf.cell(60, 6, clean_str(f"R$ {s.get('total_value', 0.0):,.2f}"), border=1, align='R', fill=fill)
            pdf.ln()
            fill = not fill

        pdf.ln(6)
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(0, 6, clean_str('2. Listagem Completa de Produtos Filtrados por Tamanho & Tipo'), border=0, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        pdf.set_font('Helvetica', 'B', 8)
        pdf.set_fill_color(30, 41, 59)
        pdf.set_text_color(255, 255, 255)
        cols_det = [
            ('SKU', 25), ('Produto', 65), ('Marca', 30), ('Fornecedor', 35),
            ('Categoria', 30), ('Tamanho', 20), ('Estoque', 20), ('P. Venda (R$)', 25), ('P. Custo (R$)', 25)
        ]
        for title, width in cols_det:
            pdf.cell(width, 6, clean_str(title), border=1, align='C', fill=True)
        pdf.ln()

        pdf.set_font('Helvetica', '', 8)
        pdf.set_text_color(15, 23, 42)
        fill = False

        for p in report_data.get('size_products_report', []):
            if pdf.get_y() > 180:
                pdf.add_page()
                pdf.set_font('Helvetica', 'B', 8)
                pdf.set_fill_color(30, 41, 59)
                pdf.set_text_color(255, 255, 255)
                for title, width in cols_det:
                    pdf.cell(width, 6, clean_str(title), border=1, align='C', fill=True)
                pdf.ln()
                pdf.set_font('Helvetica', '', 8)
                pdf.set_text_color(15, 23, 42)

            pdf.set_fill_color(248, 250, 252) if fill else pdf.set_fill_color(255, 255, 255)
            pdf.cell(25, 6, clean_str(p.get('code', '')[:14]), border=1, fill=fill)
            pdf.cell(65, 6, clean_str(p.get('name', '')[:35]), border=1, fill=fill)
            pdf.cell(30, 6, clean_str(p.get('brand', '')[:16]), border=1, fill=fill)
            pdf.cell(35, 6, clean_str(p.get('supplier_name', '')[:20]), border=1, fill=fill)
            pdf.cell(30, 6, clean_str(p.get('category', '')[:16]), border=1, fill=fill)
            pdf.cell(20, 6, clean_str(p.get('size', '')[:10]), border=1, align='C', fill=fill)
            pdf.cell(20, 6, clean_str(f"{p.get('current_stock', 0)} un"), border=1, align='R', fill=fill)
            pdf.cell(25, 6, clean_str(f"R$ {p.get('price', 0.0):,.2f}"), border=1, align='R', fill=fill)
            pdf.cell(25, 6, clean_str(f"R$ {p.get('cost_price', 0.0):,.2f}"), border=1, align='R', fill=fill)
            pdf.ln()
            fill = not fill

        filename = "relatorio_produtos_por_tamanho.pdf"

    pdf_bytes = pdf.output()
    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )



