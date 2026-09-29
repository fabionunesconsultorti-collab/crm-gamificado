import requests
import json
import logging
from datetime import datetime, date
from typing import Optional, Dict, Any

from app import db
from app.models import Client, ExternalEntityMap, BlingSalesCache, IntegrationConfig, BlingProductCache
from app.integrations.base import BaseIntegrationAdapter
from app.integrations.manager import IntegrationManager
from app.utils.lead_enricher import LeadEnricher

logger = logging.getLogger(__name__)

@IntegrationManager.register
class BlingAdapter(BaseIntegrationAdapter):
    provider_name = "bling"
    display_name = "Bling ERP"
    description = "Integração completa com Bling ERP v3: Sincronização bi-direcional de Clientes, Pedidos de Venda e Dashboards."

    BASE_URL_V3 = "https://api.bling.com.br/v3"
    BASE_URL_V2 = "https://api.bling.com.br/v2"

    def _get_headers(self, config: IntegrationConfig) -> Dict[str, str]:
        """Gera os headers HTTP para autenticação na API v3 do Bling."""
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        if config.access_token:
            headers["Authorization"] = f"Bearer {config.access_token}"
        return headers

    def test_connection(self) -> dict:
        """Testa se as credenciais cadastradas conseguem se comunicar com o Bling."""
        config = self.get_config()
        if not config.access_token and not config.api_key:
            return {
                "success": False,
                "message": "Nenhum Access Token ou API Key configurado para o Bling ERP."
            }

        try:
            # Tenta consultar o endpoint de contatos com limite=1
            headers = self._get_headers(config)
            url = f"{self.BASE_URL_V3}/contatos"
            params = {"limite": 1}

            if not config.access_token and config.api_key:
                # Fallback v2
                url = f"{self.BASE_URL_V2}/contatos/json/"
                params = {"apikey": config.api_key}

            response = requests.get(url, headers=headers, params=params, timeout=10)

            if response.status_code in [200, 201]:
                self.log('test_connection', 'success', 'Conexão com o Bling efetuada com sucesso.')
                return {
                    "success": True,
                    "message": "Conexão com o ERP Bling realizada com sucesso!"
                }
            elif response.status_code == 401:
                return {
                    "success": False,
                    "message": "Erro 401: Token ou API Key inválido/expirado."
                }
            else:
                msg = f"Resposta inesperada do Bling ({response.status_code}): {response.text[:200]}"
                self.log('test_connection', 'warning', msg)
                return {"success": False, "message": msg}

        except Exception as e:
            err_msg = f"Falha na comunicação com o Bling: {str(e)}"
            self.log('test_connection', 'error', err_msg)
            return {"success": False, "message": err_msg}

    def on_toggle(self, active: bool) -> dict:
        """
        Callback disparado ao ativar ou desativar a integração do Bling.
        - Desativar: Purga o cache local de vendas e produtos do Bling ERP.
        - Ativar: Executa a sincronização completa inicial dos dados.
        """
        if not active:
            try:
                BlingSalesCache.query.delete()
                BlingProductCache.query.delete()
                db.session.commit()
                self.log('on_toggle', 'info', 'Cache do Bling limpo com sucesso após inativação.')
                return {
                    'success': True,
                    'message': 'Integração com o Bling ERP desativada e dados locais desatualizados purgados com sucesso.'
                }
            except Exception as e:
                db.session.rollback()
                logger.error(f"[BlingAdapter] Erro ao purgar cache no on_toggle: {e}")
                return {'success': False, 'message': f'Integração desativada, mas falhou ao limpar cache: {e}'}
        else:
            self.log('on_toggle', 'info', 'Integração ativada.')
            return {
                'success': True,
                'message': 'Integração com o Bling ERP ativada com sucesso!'
            }

    def get_remote_totals(self) -> dict:
        """
        Consulta os totais de registros (Produtos, Contatos, Pedidos) cadastrados no Bling ERP
        para permitir o acompanhamento exato da progressão de importação.
        """
        if not self.is_enabled():
            return {"total_products": 0, "total_contacts": 0, "total_sales": 0}

        config = self.get_config()
        headers = self._get_headers(config)

        totals = {"total_products": 0, "total_contacts": 0, "total_sales": 0}

        try:
            # 1. Total Produtos
            res_p = requests.get(f"{self.BASE_URL_V3}/produtos", headers=headers, params={"limite": 1}, timeout=5)
            if res_p.status_code in [200, 201]:
                pj = res_p.json()
                totals["total_products"] = pj.get("paginacao", {}).get("total") or len(pj.get("data", []))

            # 2. Total Contatos
            res_c = requests.get(f"{self.BASE_URL_V3}/contatos", headers=headers, params={"limite": 1}, timeout=5)
            if res_c.status_code in [200, 201]:
                cj = res_c.json()
                totals["total_contacts"] = cj.get("paginacao", {}).get("total") or len(cj.get("data", []))

            # 3. Total Pedidos
            res_s = requests.get(f"{self.BASE_URL_V3}/pedidos/vendas", headers=headers, params={"limite": 1}, timeout=5)
            if res_s.status_code in [200, 201]:
                sj = res_s.json()
                totals["total_sales"] = sj.get("paginacao", {}).get("total") or len(sj.get("data", []))

        except Exception as ex_tot:
            logger.debug(f"[BlingTotals] Erro ao consultar totais remotos do Bling: {ex_tot}")

        # Se totais remotos forem zero por limitação da chave API, usa contagem local mínima como fallback
        if totals["total_products"] == 0:
            totals["total_products"] = BlingProductCache.query.count()
        if totals["total_contacts"] == 0:
            totals["total_contacts"] = Client.query.count()
        if totals["total_sales"] == 0:
            totals["total_sales"] = BlingSalesCache.query.count()

        return totals

    def sync_clients_inbound(self, limit: Optional[int] = None) -> dict:
        """
        Puxa contatos/clientes do Bling ERP e atualiza/cria no CRM.
        Realiza deduplicação por CPF/CNPJ, telefone ou email.
        Itera por todas as páginas (100 itens por página) para buscar 100% dos dados.
        """
        if not self.is_enabled():
            return {
                "success": False,
                "message": "Integração com o Bling está desativada no Admin."
            }

        config = self.get_config()
        headers = self._get_headers(config)
        url = f"{self.BASE_URL_V3}/contatos"

        imported_count = 0
        updated_count = 0
        errors_count = 0
        page = 1
        has_more = True

        try:
            while has_more:
                params = {"limite": 100, "pagina": page}
                response = requests.get(url, headers=headers, params=params, timeout=15)
                if response.status_code not in [200, 201]:
                    err_msg = f"Erro na requisição ao Bling na página {page} ({response.status_code}): {response.text[:200]}"
                    self.log('sync_clients_inbound', 'error', err_msg)
                    if page == 1:
                        return {"success": False, "message": err_msg}
                    break

                data = response.json()
                contatos = data.get('data', []) if isinstance(data, dict) else []

                if not contatos:
                    break

                for c in contatos:
                    try:
                        bling_id = str(c.get('id', ''))
                        nome = c.get('nome', '').strip()
                        cpf_cnpj = ''.join(filter(str.isdigit, str(c.get('numeroDocumento', '') or '')))
                        email = (c.get('email') or '').strip().lower()

                        # Telefones
                        phones_data = c.get('telefones', {})
                        raw_phone = ''
                        if isinstance(phones_data, dict):
                            raw_phone = phones_data.get('celular') or phones_data.get('fixo') or ''
                        elif isinstance(phones_data, list) and phones_data:
                            raw_phone = str(phones_data[0])

                        clean_phone = ''.join(filter(str.isdigit, str(raw_phone)))

                        if not nome:
                            continue

                        # Verifica se o cliente já existe por ExternalEntityMap, CPF/CNPJ, Telefone ou E-mail
                        existing_client = None

                        # 1. Checa ExternalEntityMap
                        ext_map = ExternalEntityMap.query.filter_by(
                            provider=self.provider_name,
                            crm_entity_type='client',
                            external_id=bling_id
                        ).first()

                        if ext_map:
                            existing_client = Client.query.get(ext_map.crm_entity_id)

                        # 2. Checa por CPF/CNPJ se tiver
                        if not existing_client and cpf_cnpj:
                            existing_client = Client.query.filter_by(cpf=cpf_cnpj).first()

                        # 3. Checa por Telefone se tiver
                        if not existing_client and clean_phone:
                            # Busca clientes com telefone similar
                            candidates = Client.query.filter(Client.phone.isnot(None)).all()
                            for cand in candidates:
                                if cand.clean_phone and cand.clean_phone == clean_phone:
                                    existing_client = cand
                                    break

                        # 4. Checa por Email se tiver
                        if not existing_client and email:
                            existing_client = Client.query.filter_by(email=email).first()

                        # Endereço
                        endereco_data = c.get('endereco', {})
                        geral = endereco_data.get('geral', {}) if isinstance(endereco_data, dict) else {}
                        rua = geral.get('endereco', '')
                        num = geral.get('numero', '')
                        bairro = geral.get('bairro', '')
                        cidade = geral.get('municipio', '')
                        uf = geral.get('uf', '')
                        cep = geral.get('cep', '')

                        full_address = f"{rua}, {num} - {bairro}, {cidade}/{uf}".strip(', -/')

                        if existing_client:
                            # Atualiza dados existentes desatualizados
                            if not existing_client.cpf and cpf_cnpj:
                                existing_client.cpf = cpf_cnpj
                            if not existing_client.email and email:
                                existing_client.email = email
                            if not existing_client.address and full_address:
                                existing_client.address = full_address
                            if not existing_client.cep and cep:
                                existing_client.cep = cep
                            updated_count += 1
                            target_client = existing_client
                        else:
                            # Cria novo cliente no CRM
                            target_client = Client(
                                name=nome,
                                phone=clean_phone or None,
                                email=email or None,
                                cpf=cpf_cnpj or None,
                                address=full_address or None,
                                cep=cep or None,
                                status='contato',
                                lead_source='Bling ERP',
                                notes=f"Importado automaticamente do Bling ERP (ID Bling: {bling_id})"
                            )
                            db.session.add(target_client)
                            db.session.flush() # garante id gerado
                            imported_count += 1

                        # Cria ou atualiza ExternalEntityMap
                        if not ext_map:
                            ext_map = ExternalEntityMap(
                                provider=self.provider_name,
                                crm_entity_type='client',
                                crm_entity_id=target_client.id,
                                external_id=bling_id,
                                sync_status='synced'
                            )
                            db.session.add(ext_map)
                        else:
                            ext_map.last_synced_at = datetime.utcnow()
                            ext_map.sync_status = 'synced'

                    except Exception as ex_item:
                        logger.error(f"[BlingInbound] Erro ao processar contato ID {c.get('id')}: {ex_item}")
                        errors_count += 1

                db.session.commit()

                if len(contatos) < 100:
                    has_more = False
                else:
                    page += 1

                if limit and (imported_count + updated_count) >= limit:
                    has_more = False

            msg = f"Sincronização concluída: {imported_count} clientes importados, {updated_count} atualizados, {errors_count} erros."
            self.log('sync_clients_inbound', 'success', msg)
            return {
                "success": True,
                "message": msg,
                "imported": imported_count,
                "updated": updated_count,
                "errors": errors_count
            }

        except Exception as e:
            db.session.rollback()
            err_msg = f"Erro geral na sincronização inbound: {str(e)}"
            self.log('sync_clients_inbound', 'error', err_msg)
            return {"success": False, "message": err_msg}

    def fetch_and_sync_clients(self, limit: Optional[int] = None) -> dict:
        """Alias para sync_clients_inbound."""
        return self.sync_clients_inbound(limit=limit)

    def sync_clients_outbound(self, client_id: Optional[int] = None) -> dict:
        """
        Exporta clientes do CRM para o Bling ERP.
        Se client_id for fornecido, exporta individualmente; se None, exporta todos pendentes.
        """
        if not self.is_enabled():
            return {
                "success": False,
                "message": "Integração com o Bling está desativada no Admin."
            }

        config = self.get_config()
        headers = self._get_headers(config)

        clients_to_sync = []
        if client_id:
            c = Client.query.get(client_id)
            if c:
                clients_to_sync.append(c)
        else:
            # Pega clientes que ainda não possuem mapeamento no Bling
            synced_ids = [m.crm_entity_id for m in ExternalEntityMap.query.filter_by(provider=self.provider_name, crm_entity_type='client').all()]
            clients_to_sync = Client.query.filter(~Client.id.in_(synced_ids)).limit(50).all() if synced_ids else Client.query.limit(50).all()

        success_count = 0
        error_count = 0

        for client in clients_to_sync:
            try:
                ext_map = ExternalEntityMap.query.filter_by(
                    provider=self.provider_name,
                    crm_entity_type='client',
                    crm_entity_id=client.id
                ).first()

                # Prepara o payload para o Bling API v3
                payload = {
                    "nome": client.name,
                    "codigo": f"CRM-{client.id}",
                    "tipo": "J" if (client.cpf and len(client.cpf) > 11) else "F",
                    "numeroDocumento": client.cpf or "",
                    "email": client.email or "",
                    "telefones": {
                        "celular": client.phone or ""
                    },
                    "endereco": {
                        "geral": {
                            "endereco": client.address or "",
                            "cep": client.cep or ""
                        }
                    }
                }

                if ext_map and ext_map.external_id:
                    # PUT /contatos/{id}
                    url = f"{self.BASE_URL_V3}/contatos/{ext_map.external_id}"
                    response = requests.put(url, headers=headers, json=payload, timeout=10)
                else:
                    # POST /contatos
                    url = f"{self.BASE_URL_V3}/contatos"
                    response = requests.post(url, headers=headers, json=payload, timeout=10)

                if response.status_code in [200, 201]:
                    res_json = response.json()
                    bling_id = str(res_json.get('data', {}).get('id', '') or (ext_map.external_id if ext_map else ''))

                    if not ext_map:
                        ext_map = ExternalEntityMap(
                            provider=self.provider_name,
                            crm_entity_type='client',
                            crm_entity_id=client.id,
                            external_id=bling_id,
                            sync_status='synced'
                        )
                        db.session.add(ext_map)
                    else:
                        ext_map.sync_status = 'synced'
                        ext_map.last_synced_at = datetime.utcnow()

                    db.session.commit()
                    success_count += 1
                else:
                    error_count += 1
                    logger.error(f"[BlingOutbound] Erro ao enviar cliente {client.id}: {response.text[:200]}")

            except Exception as ex:
                db.session.rollback()
                error_count += 1
                logger.error(f"[BlingOutbound] Exceção ao exportar cliente {client.id}: {ex}")

        msg = f"Exportação concluída: {success_count} clientes exportados para o Bling com sucesso, {error_count} falhas."
        self.log('sync_clients_outbound', 'success' if error_count == 0 else 'warning', msg)
        return {
            "success": True,
            "message": msg,
            "exported": success_count,
            "errors": error_count
        }

    def fetch_sales_reports(self, start_date=None, end_date=None, limit: Optional[int] = None) -> dict:
        """
        Busca todos os pedidos de venda do Bling (`GET /pedidos/vendas`) paginados
        e salva no BlingSalesCache.
        """
        if not self.is_enabled():
            return {
                "success": False,
                "message": "Integração com o Bling está desativada no Admin."
            }

        config = self.get_config()
        headers = self._get_headers(config)
        url = f"{self.BASE_URL_V3}/pedidos/vendas"

        saved_count = 0
        page = 1
        has_more = True

        try:
            while has_more:
                params = {"limite": 100, "pagina": page}
                response = requests.get(url, headers=headers, params=params, timeout=15)
                if response.status_code not in [200, 201]:
                    err_msg = f"Erro ao buscar pedidos no Bling na página {page} ({response.status_code}): {response.text[:200]}"
                    self.log('fetch_sales_reports', 'error', err_msg)
                    if page == 1:
                        return {"success": False, "message": err_msg}
                    break

                data = response.json()
                pedidos = data.get('data', []) if isinstance(data, dict) else []

                if not pedidos:
                    break

                for p in pedidos:
                    try:
                        bling_order_id = str(p.get('id', ''))
                        numero = str(p.get('numero', ''))
                        total = float(p.get('total', 0.0) or 0.0)
                        data_pedido_str = p.get('data', '')

                        order_date = None
                        if data_pedido_str:
                            try:
                                order_date = datetime.strptime(data_pedido_str[:10], '%Y-%m-%d').date()
                            except Exception:
                                order_date = date.today()

                        contato = p.get('contato', {})
                        client_name = contato.get('nome', '') if isinstance(contato, dict) else ''
                        cpf_cnpj = contato.get('numeroDocumento', '') if isinstance(contato, dict) else ''

                        sit = p.get('situacao', {})
                        status_name = sit.get('nome', 'Em aberto') if isinstance(sit, dict) else 'Em aberto'

                        vendedor = p.get('vendedor', {})
                        seller_name = vendedor.get('nome', '') if isinstance(vendedor, dict) else ''

                        # Salva ou atualiza no cache
                        cache_item = BlingSalesCache.query.filter_by(bling_order_id=bling_order_id).first()
                        if not cache_item:
                            cache_item = BlingSalesCache(
                                bling_order_id=bling_order_id,
                                order_number=numero,
                                client_cpf_cnpj=cpf_cnpj,
                                client_name=client_name,
                                total_value=total,
                                order_date=order_date,
                                status=status_name,
                                seller_name=seller_name,
                                raw_json=json.dumps(p)
                            )
                            db.session.add(cache_item)
                        else:
                            cache_item.order_number = numero
                            cache_item.total_value = total
                            cache_item.status = status_name
                            cache_item.updated_at = datetime.utcnow()

                        saved_count += 1
                    except Exception as ex_p:
                        logger.error(f"[BlingSales] Erro ao salvar pedido {p.get('id')}: {ex_p}")

                db.session.commit()

                if len(pedidos) < 100:
                    has_more = False
                else:
                    page += 1

                if limit and saved_count >= limit:
                    has_more = False

            msg = f"{saved_count} pedidos de venda sincronizados com o cache local."
            self.log('fetch_sales_reports', 'success', msg)
            return {"success": True, "message": msg, "total_orders": saved_count}

        except Exception as e:
            db.session.rollback()
            err_msg = f"Falha ao consultar pedidos de venda do Bling: {str(e)}"
            self.log('fetch_sales_reports', 'error', err_msg)
            return {"success": False, "message": err_msg}

    def fetch_sales_orders(self, limit: Optional[int] = None) -> dict:
        """Alias para fetch_sales_reports."""
        return self.fetch_sales_reports(limit=limit)

    def get_dashboard_metrics(self) -> dict:
        """
        Calcula os KPIs e dados para gráficos do Bling Dashboard.
        """
        sales = BlingSalesCache.query.all()
        total_faturamento = sum(s.total_value for s in sales)
        total_pedidos = len(sales)
        ticket_medio = (total_faturamento / total_pedidos) if total_pedidos > 0 else 0.0

        # Clientes top 10 (Curva ABC)
        client_totals = {}
        for s in sales:
            cname = s.client_name or "Desconhecido"
            client_totals[cname] = client_totals.get(cname, 0.0) + (s.total_value or 0.0)

        top_clients = sorted(
            [{"name": k, "total": round(v, 2)} for k, v in client_totals.items()],
            key=lambda x: x['total'],
            reverse=True
        )[:10]

        # Status dos pedidos
        status_counts = {}
        for s in sales:
            st = s.status or "Em Aberto"
            status_counts[st] = status_counts.get(st, 0) + 1

        status_chart = [{"status": k, "count": v} for k, v in status_counts.items()]

        # Clientes sincronizados
        synced_clients_count = ExternalEntityMap.query.filter_by(
            provider=self.provider_name,
            crm_entity_type='client'
        ).count()

        return {
            "total_faturamento": round(total_faturamento, 2),
            "total_pedidos": total_pedidos,
            "ticket_medio": round(ticket_medio, 2),
            "synced_clients": synced_clients_count,
            "top_clients": top_clients,
            "status_chart": status_chart,
            "recent_sales": [s.to_dict() for s in sorted(sales, key=lambda x: x.created_at or datetime.min, reverse=True)[:20]]
        }

    def _extract_brand(self, p: dict) -> str:
        if not isinstance(p, dict):
            return 'Não Informada'
        brand_val = p.get('marca') or p.get('brand')
        if isinstance(brand_val, dict):
            return brand_val.get('nome') or brand_val.get('descricao') or 'Não Informada'
        elif isinstance(brand_val, str) and brand_val.strip():
            return brand_val.strip()
        return 'Não Informada'

    def _extract_category(self, p: dict) -> str:
        if not isinstance(p, dict):
            return 'Geral'
        cat_val = p.get('categoria') or p.get('category')
        if isinstance(cat_val, dict):
            return cat_val.get('descricao') or cat_val.get('nome') or 'Geral'
        elif isinstance(cat_val, str) and cat_val.strip():
            return cat_val.strip()
        return 'Geral'

    def _extract_supplier(self, p: dict) -> str:
        if not isinstance(p, dict):
            return 'Não Informado'
        sup_val = p.get('fornecedor') or p.get('supplier')
        if isinstance(sup_val, dict):
            return sup_val.get('nome') or sup_val.get('razaoSocial') or sup_val.get('contato', {}).get('nome') or 'Não Informado'
        elif isinstance(sup_val, str) and sup_val.strip():
            return sup_val.strip()

        sups = p.get('fornecedores')
        if isinstance(sups, list) and len(sups) > 0:
            first_sup = sups[0]
            if isinstance(first_sup, dict):
                return first_sup.get('nome') or first_sup.get('fornecedor', {}).get('nome') or 'Não Informado'

        return 'Não Informado'

    def _extract_product_size(self, p: dict) -> str:
        if not isinstance(p, dict):
            return 'Único'

        # 1. Campo explícito
        if p.get('tamanho') and str(p['tamanho']).strip():
            return str(p['tamanho']).strip().upper()
        if p.get('grade') and str(p['grade']).strip():
            return str(p['grade']).strip().upper()

        # 2. Variações / Atributos de Variação
        variacao = p.get('variacao') or p.get('variacoes')
        if isinstance(variacao, dict):
            v_nome = variacao.get('nome') or variacao.get('atributos', {}).get('tamanho')
            if v_nome and str(v_nome).strip():
                return str(v_nome).strip().upper()
        elif isinstance(variacao, list) and len(variacao) > 0:
            first_var = variacao[0]
            if isinstance(first_var, dict):
                v_nome = first_var.get('nome') or first_var.get('tamanho')
                if v_nome and str(v_nome).strip():
                    return str(v_nome).strip().upper()

        # 3. Atributos customizados
        atributos = p.get('atributos', [])
        if isinstance(atributos, list):
            for attr in atributos:
                if isinstance(attr, dict) and str(attr.get('nome', '')).lower() in ['tamanho', 'grade', 'size', 'tam']:
                    if attr.get('valor'):
                        return str(attr['valor']).strip().upper()

        # 4. Regex / Padrões no Nome ou Código
        name = str(p.get('nome', '') or '')
        code = str(p.get('codigo', '') or '')
        full_text = f"{code} {name}".upper()

        import re
        patterns = [
            r'(?:TAM|TAMANHO|GRADE)[\s\:\-\/]+([0-9]{2}|PP|P|M|G|GG|XG|XXG|EXG|ÚNICO|UNICO)',
            r'[\s\-\/\(](PP|P|M|G|GG|XG|XXG|EXG|34|35|36|37|38|39|40|41|42|43|44|45|46|48|50)[\s\-\/\)]*$',
            r'[\s\-\/](3[4-9]|4[0-8]|5[0-4])\b'
        ]
        for pat in patterns:
            m = re.search(pat, full_text)
            if m:
                return m.group(1).strip()

        return 'Único'

    def fetch_products_and_stock(self, limit: Optional[int] = None) -> dict:
        """
        Busca a lista de produtos e saldos de estoque do Bling ERP (`GET /produtos`) paginada
        e atualiza a tabela BlingProductCache.
        """
        if not self.is_enabled():
            return {"success": False, "message": "Integração desacoplada com o Bling está inativa."}

        config = self.get_config()
        headers = self._get_headers(config)
        url = f"{self.BASE_URL_V3}/produtos"

        saved_count = 0
        page = 1
        has_more = True

        try:
            while has_more:
                params = {"limite": 100, "pagina": page}
                response = requests.get(url, headers=headers, params=params, timeout=15)
                if response.status_code not in [200, 201]:
                    err_msg = f"Erro ao buscar produtos no Bling na página {page} ({response.status_code}): {response.text[:200]}"
                    self.log('fetch_products_and_stock', 'error', err_msg)
                    if page == 1:
                        return {"success": False, "message": err_msg}
                    break

                data = response.json()
                produtos = data.get('data', []) if isinstance(data, dict) else []

                if not produtos:
                    break

                for p in produtos:
                    try:
                        bling_product_id = str(p.get('id', ''))
                        nome = p.get('nome', '').strip()
                        codigo = str(p.get('codigo', '') or '').strip()
                        preco = float(p.get('preco', 0.0) or 0.0)
                        preco_custo = float(p.get('precoCusto', 0.0) or 0.0)

                        marca = self._extract_brand(p)
                        categoria = self._extract_category(p)
                        fornecedor = self._extract_supplier(p)
                        tamanho = self._extract_product_size(p)

                        estoque_data = p.get('estoque', {})
                        saldo_estoque = 0
                        if isinstance(estoque_data, dict):
                            saldo_estoque = int(estoque_data.get('saldoFisicoTotal') or estoque_data.get('saldoVirtualTotal') or 0)
                        elif isinstance(estoque_data, (int, float)):
                            saldo_estoque = int(estoque_data)

                        cache_p = BlingProductCache.query.filter_by(bling_product_id=bling_product_id).first()
                        days_without_sale = cache_p.days_without_sale if cache_p else 30

                        if not cache_p:
                            cache_p = BlingProductCache(
                                bling_product_id=bling_product_id,
                                code=codigo,
                                name=nome,
                                brand=marca,
                                supplier_name=fornecedor,
                                category=categoria,
                                size=tamanho,
                                price=preco,
                                cost_price=preco_custo,
                                current_stock=saldo_estoque,
                                days_without_sale=days_without_sale,
                                raw_json=json.dumps(p)
                            )
                            db.session.add(cache_p)
                        else:
                            cache_p.name = nome
                            cache_p.code = codigo
                            cache_p.brand = marca
                            cache_p.supplier_name = fornecedor
                            cache_p.category = categoria
                            cache_p.size = tamanho
                            cache_p.price = preco
                            cache_p.cost_price = preco_custo
                            cache_p.current_stock = saldo_estoque
                            cache_p.updated_at = datetime.utcnow()

                        saved_count += 1
                    except Exception as ex_item:
                        logger.error(f"[BlingProducts] Erro ao sincronizar produto {p.get('id')}: {ex_item}")

                db.session.commit()

                if len(produtos) < 100:
                    has_more = False
                else:
                    page += 1

                if limit and saved_count >= limit:
                    has_more = False

            msg = f"{saved_count} produtos e saldos de estoque sincronizados."
            self.log('fetch_products_and_stock', 'success', msg)
            return {"success": True, "message": msg, "total_products": saved_count}

        except Exception as e:
            db.session.rollback()
            err_msg = f"Falha ao consultar produtos no Bling: {str(e)}"
            self.log('fetch_products_and_stock', 'error', err_msg)
            return {"success": False, "message": err_msg}

    def get_decision_reports_data(self, filters: Optional[dict] = None) -> dict:
        """
        Gera os 3 relatórios de tomada de decisão com filtros dinâmicos e cruzados:
        1. Relatório de Estoque Parado (por Marca, Fornecedor, Categoria, Dias Parado)
        2. Relatório de Análise de Clientes (Últimas Compras, Ticket Médio, Melhores Compradores)
        3. Relatório por Tamanho / Tipo de Produto (Filtros Cruzados: Tamanho, Categoria, Marca, Fornecedor, Dias)
        """
        filters = filters or {}

        # ── 1. RELATÓRIO DE ESTOQUE PARADO ─────────────────────────────
        query_stock = BlingProductCache.query

        brand_filter = filters.get('brand')
        if brand_filter and brand_filter != 'all':
            query_stock = query_stock.filter(BlingProductCache.brand == brand_filter)

        supplier_filter = filters.get('supplier')
        if supplier_filter and supplier_filter != 'all':
            query_stock = query_stock.filter(BlingProductCache.supplier_name == supplier_filter)

        category_filter = filters.get('category')
        if category_filter and category_filter != 'all':
            query_stock = query_stock.filter(BlingProductCache.category == category_filter)

        min_days = filters.get('min_days')
        if min_days and min_days not in ['0', 'all', '', None]:
            try:
                query_stock = query_stock.filter(BlingProductCache.days_without_sale >= int(min_days))
            except Exception: pass

        stock_items = query_stock.order_by(BlingProductCache.current_stock.desc()).all()

        total_capital_parado = sum((p.current_stock or 0) * (p.cost_price or p.price or 0.0) for p in stock_items)
        total_pecas_paradas = sum((p.current_stock or 0) for p in stock_items)

        # Opções dinâmicas para filtros
        all_brands = sorted(list(set(p.brand for p in BlingProductCache.query.all() if p.brand)))
        all_suppliers = sorted(list(set(p.supplier_name for p in BlingProductCache.query.all() if p.supplier_name)))
        all_categories = sorted(list(set(p.category for p in BlingProductCache.query.all() if p.category)))
        all_sizes = sorted(list(set(p.size for p in BlingProductCache.query.all() if p.size)))

        # ── 2. RELATÓRIO DE ANÁLISE DE CLIENTES & AUTO-CADASTRO NO CRM ─
        sales = BlingSalesCache.query.all()
        client_metrics = {}

        for s in sales:
            cname = s.client_name or "Cliente Não Identificado"
            doc = s.client_cpf_cnpj or ""
            val = s.total_value or 0.0
            dt = s.order_date or date.today()

            if cname not in client_metrics:
                client_metrics[cname] = {
                    "client_name": cname,
                    "cpf_cnpj": doc,
                    "total_spent": 0.0,
                    "total_orders": 0,
                    "last_purchase_date": dt,
                    "ticket_medio": 0.0,
                    "status_rfm": "Ativo"
                }

            cm = client_metrics[cname]
            cm["total_spent"] += val
            cm["total_orders"] += 1
            if dt > cm["last_purchase_date"]:
                cm["last_purchase_date"] = dt

        # Garante auto-cadastro de todos os clientes importados do Bling na base do CRM
        for cname, cm in client_metrics.items():
            if cname and cname != "Cliente Não Identificado":
                doc = cm.get("cpf_cnpj") or ""
                crm_cli = None
                if doc:
                    crm_cli = Client.query.filter_by(cpf=doc).first()
                if not crm_cli:
                    crm_cli = Client.query.filter_by(name=cname).first()

                if not crm_cli:
                    try:
                        crm_cli = Client(
                            name=cname,
                            cpf=doc or None,
                            status='contato',
                            lead_source='Bling ERP',
                            ltv=cm.get("total_spent", 0.0),
                            purchase_frequency=cm.get("total_orders", 0),
                            last_purchase_date=cm.get("last_purchase_date"),
                            notes="Cadastrado automaticamente a partir da Análise de Clientes do Bling ERP"
                        )
                        db.session.add(crm_cli)
                        db.session.commit()
                    except Exception:
                        db.session.rollback()

        # Enriquece o relatório com os clientes cadastrados no CRM
        for cli in Client.query.all():
            cname = cli.name or "Cliente"
            if cname not in client_metrics:
                val = cli.ltv or 0.0
                orders = cli.purchase_frequency or (1 if val > 0 else 0)
                dt = cli.last_purchase_date or (cli.created_at.date() if cli.created_at else date.today())
                client_metrics[cname] = {
                    "client_name": cname,
                    "cpf_cnpj": cli.cpf or "",
                    "total_spent": val,
                    "total_orders": orders,
                    "last_purchase_date": dt,
                    "ticket_medio": round(val / orders, 2) if orders > 0 else val,
                    "status_rfm": "Ativo"
                }

        now_date = date.today()
        clients_report = []

        for cname, cm in client_metrics.items():
            cm["ticket_medio"] = round(cm["total_spent"] / cm["total_orders"], 2) if cm["total_orders"] > 0 else 0.0
            days_since = (now_date - cm["last_purchase_date"]).days

            if days_since > 60:
                cm["status_rfm"] = "Risco de Churn"
            elif cm["total_spent"] > 1000 or cm["total_orders"] >= 3:
                cm["status_rfm"] = "Melhor Comprador (VIP)"
            elif cm["total_orders"] == 1 and days_since <= 30:
                cm["status_rfm"] = "Novo Cliente"
            else:
                cm["status_rfm"] = "Recorrente"

            cm["days_since_last"] = days_since
            cm["last_purchase_str"] = cm["last_purchase_date"].strftime('%d/%m/%Y')
            cm["total_spent_str"] = f"R$ {cm['total_spent']:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
            cm["ticket_medio_str"] = f"R$ {cm['ticket_medio']:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
            clients_report.append(cm)

        rfm_filter = filters.get('rfm_status')
        if rfm_filter and rfm_filter != 'all':
            clients_report = [c for c in clients_report if c['status_rfm'] == rfm_filter]

        clients_report = sorted(clients_report, key=lambda x: x['total_spent'], reverse=True)

        # ── 3. RELATÓRIO POR TAMANHO E TIPO DE PRODUTO (FILTROS CRUZADOS) ────
        query_size = BlingProductCache.query

        size_filter = filters.get('size')
        if size_filter and size_filter != 'all':
            query_size = query_size.filter(BlingProductCache.size == size_filter)

        category_filter = filters.get('category')
        if category_filter and category_filter != 'all':
            query_size = query_size.filter(BlingProductCache.category == category_filter)

        brand_filter = filters.get('brand')
        if brand_filter and brand_filter != 'all':
            query_size = query_size.filter(BlingProductCache.brand == brand_filter)

        supplier_filter = filters.get('supplier')
        if supplier_filter and supplier_filter != 'all':
            query_size = query_size.filter(BlingProductCache.supplier_name == supplier_filter)

        min_days = filters.get('min_days')
        if min_days and min_days not in ['0', 'all', '', None]:
            try:
                query_size = query_size.filter(BlingProductCache.days_without_sale >= int(min_days))
            except Exception: pass

        size_items = query_size.all()

        size_summary = {}
        for p in size_items:
            sz = p.size or "Único"
            cat = p.category or "Geral"
            key = f"{cat} - {sz}"

            if key not in size_summary:
                size_summary[key] = {
                    "category": cat,
                    "size": sz,
                    "total_stock": 0,
                    "products_count": 0,
                    "total_value": 0.0
                }

            size_summary[key]["total_stock"] += (p.current_stock or 0)
            size_summary[key]["products_count"] += 1
            size_summary[key]["total_value"] += (p.current_stock or 0) * (p.price or 0.0)

        size_report = sorted(list(size_summary.values()), key=lambda x: x['total_stock'], reverse=True)
        size_products_report = [p.to_dict() for p in size_items]

        return {
            "stock_report": [p.to_dict() for p in stock_items],
            "total_capital_parado": round(total_capital_parado, 2),
            "total_pecas_paradas": total_pecas_paradas,
            "clients_report": clients_report,
            "size_report": size_report,
            "size_products_report": size_products_report,
            "filters_options": {
                "brands": all_brands,
                "suppliers": all_suppliers,
                "categories": all_categories,
                "sizes": all_sizes
            }
        }


    def process_webhook_event(self, payload: dict) -> dict:
        """
        Recebe e processa eventos enviados via Webhook pelo Bling ERP:
        - Clientes / Contatos / Fornecedores (Criação, Atualização, Exclusão)
        - Pedidos de Venda (Criação, Atualização, Exclusão)
        - Produtos / Estoque (Criação, Atualização, Exclusão)
        """
        if not self.is_enabled():
            return {"success": False, "message": "Integração desacoplada com o Bling está inativa."}

        try:
            event_name = str(payload.get('event') or payload.get('type') or payload.get('action') or '').lower()
            data_obj = payload.get('data') or payload.get('retorno') or payload

            entity_id = None
            if isinstance(data_obj, dict):
                entity_id = data_obj.get('id') or data_obj.get('idContato') or data_obj.get('idPedido')
            if not entity_id:
                entity_id = payload.get('id') or payload.get('dataId')

            entity_id_str = str(entity_id) if entity_id else ''

            self.log('webhook_received', 'info', f"Webhook Bling recebido: Evento='{event_name}', Entity ID='{entity_id_str}'")

            # 1. Trata Contatos e Fornecedores
            if any(k in event_name for k in ['contato', 'fornecedor', 'cliente']):
                if 'exclus' in event_name or 'delete' in event_name:
                    if entity_id_str:
                        ext_map = ExternalEntityMap.query.filter_by(
                            provider=self.provider_name,
                            crm_entity_type='client',
                            external_id=entity_id_str
                        ).first()
                        if ext_map:
                            ext_map.sync_status = 'deleted'
                            db.session.commit()
                    self.log('webhook_contact_deleted', 'warning', f"Contato ID {entity_id_str} excluído no Bling.")
                else:
                    self.sync_contact_by_id(entity_id_str)

            # 2. Trata Pedidos de Venda
            elif any(k in event_name for k in ['pedido', 'venda', 'order']):
                if 'exclus' in event_name or 'delete' in event_name:
                    if entity_id_str:
                        cache_item = BlingSalesCache.query.filter_by(bling_order_id=entity_id_str).first()
                        if cache_item:
                            cache_item.status = 'Cancelado/Excluído'
                            db.session.commit()
                    self.log('webhook_order_deleted', 'warning', f"Pedido ID {entity_id_str} excluído no Bling.")
                else:
                    self.sync_order_by_id(entity_id_str)

            # 3. Trata Estoque e Produtos
            elif any(k in event_name for k in ['estoque', 'produto', 'stock']):
                msg = f"Evento de Estoque/Produto recebido: '{event_name}' para ID {entity_id_str}."
                self.log('webhook_stock_update', 'info', msg)

            else:
                msg = f"Webhook Bling recebido e registrado: {json.dumps(payload)[:200]}"
                self.log('webhook_generic', 'info', msg)

            return {"success": True, "message": "Webhook processado com sucesso.", "event": event_name, "entity_id": entity_id_str}

        except Exception as e:
            err_msg = f"Erro ao processar Webhook do Bling: {str(e)}"
            self.log('webhook_error', 'error', err_msg)
            return {"success": False, "message": err_msg}

    def sync_contact_by_id(self, contact_id: str) -> dict:
        """Busca os detalhes de um contato individual no Bling via API e sincroniza com o CRM."""
        if not contact_id:
            return {"success": False, "message": "ID do contato não fornecido."}

        config = self.get_config()
        headers = self._get_headers(config)
        url = f"{self.BASE_URL_V3}/contatos/{contact_id}"

        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code not in [200, 201]:
                err = f"Falha ao consultar contato {contact_id} no Bling ({response.status_code})"
                self.log('sync_contact_by_id', 'warning', err)
                return {"success": False, "message": err}

            c = response.json().get('data', {})
            if not c:
                return {"success": False, "message": "Dados do contato vazios."}

            nome = c.get('nome', '').strip()
            cpf_cnpj = ''.join(filter(str.isdigit, str(c.get('numeroDocumento', '') or '')))
            email = (c.get('email') or '').strip().lower()

            phones_data = c.get('telefones', {})
            raw_phone = ''
            if isinstance(phones_data, dict):
                raw_phone = phones_data.get('celular') or phones_data.get('fixo') or ''
            clean_phone = ''.join(filter(str.isdigit, str(raw_phone)))

            ext_map = ExternalEntityMap.query.filter_by(
                provider=self.provider_name,
                crm_entity_type='client',
                external_id=contact_id
            ).first()

            existing_client = Client.query.get(ext_map.crm_entity_id) if ext_map else None

            if not existing_client and cpf_cnpj:
                existing_client = Client.query.filter_by(cpf=cpf_cnpj).first()
            if not existing_client and clean_phone:
                for cand in Client.query.filter(Client.phone.isnot(None)).all():
                    if cand.clean_phone and cand.clean_phone == clean_phone:
                        existing_client = cand
                        break

            if existing_client:
                if not existing_client.cpf and cpf_cnpj: existing_client.cpf = cpf_cnpj
                if not existing_client.email and email: existing_client.email = email
                target_client = existing_client
            else:
                target_client = Client(
                    name=nome or f"Contato Bling #{contact_id}",
                    phone=clean_phone or None,
                    email=email or None,
                    cpf=cpf_cnpj or None,
                    status='contato',
                    lead_source='Bling Webhook',
                    notes=f"Criado automaticamente via Webhook do Bling ERP (ID: {contact_id})"
                )
                db.session.add(target_client)
                db.session.flush()

            if not ext_map:
                ext_map = ExternalEntityMap(
                    provider=self.provider_name,
                    crm_entity_type='client',
                    crm_entity_id=target_client.id,
                    external_id=contact_id,
                    sync_status='synced'
                )
                db.session.add(ext_map)
            else:
                ext_map.last_synced_at = datetime.utcnow()
                ext_map.sync_status = 'synced'

            db.session.commit()
            self.log('sync_contact_by_id', 'success', f"Cliente '{target_client.name}' sincronizado via Webhook.")
            return {"success": True, "client_id": target_client.id}

        except Exception as ex:
            db.session.rollback()
            return {"success": False, "message": str(ex)}

    def sync_order_by_id(self, order_id: str) -> dict:
        """Busca os detalhes de um pedido individual no Bling via API e atualiza o BlingSalesCache."""
        if not order_id:
            return {"success": False, "message": "ID do pedido não fornecido."}

        config = self.get_config()
        headers = self._get_headers(config)
        url = f"{self.BASE_URL_V3}/pedidos/vendas/{order_id}"

        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code not in [200, 201]:
                err = f"Falha ao consultar pedido {order_id} no Bling ({response.status_code})"
                self.log('sync_order_by_id', 'warning', err)
                return {"success": False, "message": err}

            p = response.json().get('data', {})
            if not p:
                return {"success": False, "message": "Dados do pedido vazios."}

            numero = str(p.get('numero', ''))
            total = float(p.get('total', 0.0) or 0.0)
            data_str = p.get('data', '')

            order_date = date.today()
            if data_str:
                try: order_date = datetime.strptime(data_str[:10], '%Y-%m-%d').date()
                except Exception: pass

            contato = p.get('contato', {})
            client_name = contato.get('nome', '') if isinstance(contato, dict) else ''
            cpf_cnpj = contato.get('numeroDocumento', '') if isinstance(contato, dict) else ''

            sit = p.get('situacao', {})
            status_name = sit.get('nome', 'Em aberto') if isinstance(sit, dict) else 'Em aberto'

            vendedor = p.get('vendedor', {})
            seller_name = vendedor.get('nome', '') if isinstance(vendedor, dict) else ''

            cache_item = BlingSalesCache.query.filter_by(bling_order_id=order_id).first()
            if not cache_item:
                cache_item = BlingSalesCache(
                    bling_order_id=order_id,
                    order_number=numero,
                    client_cpf_cnpj=cpf_cnpj,
                    client_name=client_name,
                    total_value=total,
                    order_date=order_date,
                    status=status_name,
                    seller_name=seller_name,
                    raw_json=json.dumps(p)
                )
                db.session.add(cache_item)
            else:
                cache_item.order_number = numero
                cache_item.total_value = total
                cache_item.status = status_name
                cache_item.updated_at = datetime.utcnow()

            db.session.commit()
            self.log('sync_order_by_id', 'success', f"Pedido #{numero} (ID: {order_id}) atualizado via Webhook.")
            return {"success": True, "order_id": order_id}

        except Exception as ex:
            db.session.rollback()
            return {"success": False, "message": str(ex)}

