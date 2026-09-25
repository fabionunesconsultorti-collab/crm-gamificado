import os
import io
import csv
import json
import logging
import requests
from flask import current_app

logger = logging.getLogger(__name__)

class MapsScraperClient:
    """
    Cliente HTTP para integração com a API REST do Google Maps Scraper
    (gosom/google-maps-scraper rodando em container Docker).
    """

    def __init__(self, base_url=None, timeout=30):
        self.timeout = timeout
        if base_url:
            self.base_url = base_url.rstrip('/')
        else:
            try:
                if current_app and 'MAPS_SCRAPER_URL' in current_app.config:
                    self.base_url = current_app.config['MAPS_SCRAPER_URL'].rstrip('/')
                else:
                    self.base_url = os.environ.get('MAPS_SCRAPER_URL', 'http://localhost:8080').rstrip('/')
            except RuntimeError:
                self.base_url = os.environ.get('MAPS_SCRAPER_URL', 'http://localhost:8080').rstrip('/')

    def is_online(self) -> bool:
        """Verifica se o serviço do scraper está acessível."""
        try:
            resp = requests.get(f"{self.base_url}/api/v1/jobs", timeout=5)
            return resp.status_code == 200
        except Exception as e:
            logger.warning(f"[MapsScraper] Serviço indisponível em {self.base_url}: {e}")
            return False

    def create_job(self, queries: list[str], depth: int = 1, extract_emails: bool = True, name: str = None, proxies: list[str] = None) -> str:
        """
        Cria um novo job de scraping de Google Maps.
        Retorna o UUID do job criado.
        """
        if isinstance(queries, str):
            queries = [queries]

        job_name = name or (queries[0] if queries else "Busca Google Maps")
        payload = {
            "name": job_name,
            "keywords": queries,
            "lang": "pt",
            "zoom": 15,
            "depth": max(1, min(int(depth or 1), 10)),
            "email": bool(extract_emails),
            "max_time": 3600,
            "proxies": proxies or []
        }

        url = f"{self.base_url}/api/v1/jobs"
        logger.info(f"[MapsScraper] Enviando POST {url} com {len(queries)} palavras-chave (depth={depth}, email={extract_emails})")

        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
            if resp.status_code in (200, 201):
                data = resp.json()
                job_id = data.get("id")
                if not job_id:
                    raise ValueError(f"Resposta da API sem campo 'id': {resp.text}")
                logger.info(f"[MapsScraper] Job criado com sucesso: ID={job_id}")
                return str(job_id)
            else:
                error_msg = f"Erro ao criar job ({resp.status_code}): {resp.text}"
                logger.error(f"[MapsScraper] {error_msg}")
                raise RuntimeError(error_msg)
        except requests.RequestException as e:
            logger.error(f"[MapsScraper] Falha de conexão ao criar job: {e}")
            raise

    def check_status(self, job_id: str) -> dict:
        """
        Consulta o status atual de um job específico.
        Retorna um dicionário contendo o status ('completed', 'running', 'failed', 'pending', etc.)
        """
        url = f"{self.base_url}/api/v1/jobs/{job_id}"
        try:
            resp = requests.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json() or {}
                # O gosom pode retornar status como 'ok', 'working', 'completed', 'running', 'failed'
                raw_status = (data.get("status") or data.get("Status") or "").lower()
                
                # Normalização de status para o padrão do CRM
                if raw_status in ("ok", "completed", "done", "success"):
                    normalized_status = "completed"
                elif raw_status in ("running", "in_progress", "processing", "working"):
                    normalized_status = "processing"
                elif raw_status in ("failed", "error"):
                    normalized_status = "failed"
                else:
                    normalized_status = raw_status or "processing"

                return {
                    "ok": True,
                    "job_id": job_id,
                    "status": normalized_status,
                    "raw_status": raw_status,
                    "data": data
                }
            elif resp.status_code == 404:
                return {"ok": False, "job_id": job_id, "status": "not_found", "error": "Job não encontrado no scraper"}
            else:
                return {"ok": False, "job_id": job_id, "status": "error", "error": f"HTTP {resp.status_code}: {resp.text}"}
        except requests.RequestException as e:
            logger.warning(f"[MapsScraper] Erro ao consultar status do job {job_id}: {e}")
            return {"ok": False, "job_id": job_id, "status": "connection_error", "error": str(e)}

    def cancel_job(self, job_id: str) -> bool:
        """
        Cancela ou remove um job do scraper externo via DELETE /api/v1/jobs/{id}.
        Retorna True se cancelado ou já removido com sucesso.
        """
        if not job_id:
            return False
        url = f"{self.base_url}/api/v1/jobs/{job_id}"
        logger.info(f"[MapsScraper] Solicitando cancelamento do job {job_id} em {url}")
        try:
            resp = requests.delete(url, timeout=self.timeout)
            if resp.status_code in (200, 204, 404):
                logger.info(f"[MapsScraper] Job {job_id} cancelado/removido no scraper com sucesso (HTTP {resp.status_code}).")
                return True
            else:
                logger.warning(f"[MapsScraper] Resposta inesperada ao cancelar job {job_id}: {resp.status_code} - {resp.text}")
                return False
        except requests.RequestException as e:
            logger.warning(f"[MapsScraper] Falha de conexão ao comunicar cancelamento do job {job_id}: {e}")
            return False

    def fetch_results(self, job_id: str) -> list[dict]:
        """
        Faz o download dos resultados do job.
        O scraper fornece os dados via CSV pelo endpoint /api/v1/jobs/{id}/download.
        Esta função converte os dados em uma lista de dicionários limpa e padronizada.
        """
        url = f"{self.base_url}/api/v1/jobs/{job_id}/download"
        logger.info(f"[MapsScraper] Baixando resultados de {url}")

        try:
            resp = requests.get(url, timeout=60)
            if resp.status_code != 200:
                logger.error(f"[MapsScraper] Falha ao baixar resultados ({resp.status_code}): {resp.text}")
                return []

            content_type = resp.headers.get("Content-Type", "")

            # Garante decodificação UTF-8 a partir dos bytes brutos
            raw_text = ""
            if resp.content:
                for enc in ('utf-8-sig', 'utf-8', 'latin1'):
                    try:
                        raw_text = resp.content.decode(enc)
                        break
                    except (UnicodeDecodeError, LookupError):
                        continue
            if not raw_text:
                resp.encoding = 'utf-8'
                raw_text = resp.text
            
            # Se a resposta já for JSON
            if "application/json" in content_type or raw_text.strip().startswith(("[", "{")):
                try:
                    data = json.loads(raw_text)
                    if isinstance(data, list):
                        return [self._normalize_item(x) for x in data]
                    elif isinstance(data, dict) and "items" in data:
                        return [self._normalize_item(x) for x in data["items"]]
                except Exception:
                    pass

            # Processamento de CSV
            results = []
            f = io.StringIO(raw_text)
            reader = csv.DictReader(f)
            for row in reader:
                results.append(self._normalize_item(row))

            logger.info(f"[MapsScraper] {len(results)} empresas extraídas do job {job_id}")
            return results
        except requests.RequestException as e:
            logger.error(f"[MapsScraper] Exceção ao baixar resultados do job {job_id}: {e}")
            return []

    def _normalize_item(self, row: dict) -> dict:
        """Padroniza chaves comuns retornadas pelo scraper para facilitar a higienização."""
        if not isinstance(row, dict):
            return {}

        from app.utils.encoding import sanitize_encoding

        clean = {k.strip().lower().replace(' ', '_'): v for k, v in row.items() if k}

        # Extração de campos essenciais com higienização de codificação UTF-8
        name = sanitize_encoding(clean.get("title") or clean.get("name") or clean.get("business_name") or "")
        phone = clean.get("phone") or clean.get("phone_number") or clean.get("telephone") or ""
        email = clean.get("email") or clean.get("emails") or ""
        website = clean.get("website") or clean.get("web_site") or clean.get("domain") or ""
        address = sanitize_encoding(clean.get("address") or clean.get("full_address") or clean.get("street") or "")
        category = sanitize_encoding(clean.get("category") or clean.get("main_category") or clean.get("categories") or "")
        
        # Rating e reviews
        raw_rating = clean.get("total_score") or clean.get("rating") or clean.get("score") or 0.0
        try:
            rating = float(raw_rating) if raw_rating else 0.0
        except (ValueError, TypeError):
            rating = 0.0

        raw_reviews = clean.get("reviews_count") or clean.get("reviews") or clean.get("user_ratings_total") or 0
        try:
            reviews_count = int(raw_reviews) if raw_reviews else 0
        except (ValueError, TypeError):
            reviews_count = 0

        instagram = clean.get("instagram") or clean.get("ig") or clean.get("instagram_profile") or ""
        # Se website for um link direto para o Instagram e instagram não tiver sido informado
        if website and "instagram.com" in website.lower() and not instagram:
            instagram = website

        # Se email vier em lista/string delimitada
        if isinstance(email, str) and (',' in email or ';' in email):
            email = email.split(',')[0].split(';')[0].strip()

        return {
            "name": name.strip(),
            "phone": phone.strip(),
            "email": email.strip() if email else None,
            "website": website.strip() if website else None,
            "instagram": instagram.strip() if instagram else None,
            "address": address.strip() if address else None,
            "category": category.strip() if category else None,
            "rating": rating,
            "reviews_count": reviews_count,
            "raw": row
        }
