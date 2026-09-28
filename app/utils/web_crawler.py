import logging
import re
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

class WebPageExtractor:
    """
    Extrator semântico e limpador de conteúdo de websites para ingestão no RAG.
    Remove ruídos (scripts, estilos, menus, rodapés) e preserva a hierarquia textual.
    """

    DEFAULT_HEADERS = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/124.0.0.0 Safari/537.36'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
        'DNT': '1',
        'Upgrade-Insecure-Requests': '1'
    }

    STRIP_TAGS = [
        'script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript',
        'svg', 'iframe', 'form', 'button', 'input', 'select', 'textarea',
        'link', 'meta'
    ]

    @classmethod
    def sanitize_url(cls, url: str) -> str:
        """Garante que a URL comece com http:// ou https://."""
        if not url:
            return ""
        clean = url.strip()
        if not clean.startswith(('http://', 'https://')):
            clean = f"https://{clean}"
        return clean

    @classmethod
    def extract_from_url(cls, url: str, timeout: int = 15) -> dict:
        """
        Faz o download da página, limpa elementos irrelevantes e extrai o texto substantivo.
        Retorna dicionário estruturado com título, descrição e conteúdo formatado.
        """
        valid_url = cls.sanitize_url(url)
        parsed = urlparse(valid_url)
        if not parsed.netloc:
            return {'ok': False, 'error': f'URL inválida: {url}'}

        try:
            logger.info(f"[WebPageExtractor] Baixando conteúdo de '{valid_url}'...")
            resp = requests.get(
                valid_url,
                headers=cls.DEFAULT_HEADERS,
                timeout=timeout,
                allow_redirects=True
            )

            if resp.status_code != 200:
                return {
                    'ok': False,
                    'error': f'O servidor retornou status HTTP {resp.status_code} ao acessar o site.'
                }

            # Garante encoding correto
            if resp.encoding is None or resp.encoding == 'ISO-8859-1':
                resp.encoding = resp.apparent_encoding or 'utf-8'

            html_text = resp.text
            soup = BeautifulSoup(html_text, 'html.parser')

            # 1. Extração de Título
            title = ""
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
            if not title:
                h1 = soup.find('h1')
                if h1:
                    title = h1.get_text().strip()
            if not title:
                title = f"Website: {parsed.netloc}"

            # 2. Extração de Meta Description
            meta_desc = ""
            desc_tag = soup.find('meta', attrs={'name': re.compile(r'description', re.I)})
            if not desc_tag:
                desc_tag = soup.find('meta', attrs={'property': re.compile(r'og:description', re.I)})
            if desc_tag and desc_tag.get('content'):
                meta_desc = desc_tag['content'].strip()

            # 3. Limpeza de Tags Irrelevantes
            for tag in cls.STRIP_TAGS:
                for match in soup.find_all(tag):
                    match.decompose()

            # 4. Seleção da Região Principal (Main/Article se disponíveis)
            main_container = soup.find('main') or soup.find('article') or soup.find('div', id=re.compile(r'content|main|corpo', re.I)) or soup.body
            if not main_container:
                main_container = soup

            # 5. Formatação do Conteúdo Textual
            text_lines = []
            if meta_desc:
                text_lines.append(f"Resumo da Página: {meta_desc}\n")

            # Percorre elementos substantivos
            for elem in main_container.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'li', 'td', 'blockquote']):
                text = elem.get_text().strip()
                if not text or len(text) < 3:
                    continue

                tag_name = elem.name.lower()
                if tag_name == 'h1':
                    text_lines.append(f"\n# {text}\n")
                elif tag_name == 'h2':
                    text_lines.append(f"\n## {text}\n")
                elif tag_name in ['h3', 'h4']:
                    text_lines.append(f"\n### {text}\n")
                elif tag_name == 'li':
                    text_lines.append(f"- {text}")
                elif tag_name == 'blockquote':
                    text_lines.append(f"> {text}\n")
                else:
                    text_lines.append(f"{text}\n")

            content = "\n".join(text_lines)

            # Normalização de quebras de linha e espaçamentos repetidos
            content = re.sub(r'\n{3,}', '\n\n', content).strip()

            if not content or len(content) < 40:
                # Fallback para extração de texto direto do body se os seletores não capturaram
                fallback_text = main_container.get_text(separator='\n')
                lines = [line.strip() for line in fallback_text.splitlines() if line.strip() and len(line.strip()) > 3]
                content = "\n".join(lines)
                content = re.sub(r'\n{3,}', '\n\n', content).strip()

            if not content or len(content) < 30:
                return {
                    'ok': False,
                    'error': 'Não foi possível extrair conteúdo textual legível desta página web (pode ser renderizada exclusivamente por Javascript/SPA).'
                }

            full_document_text = (
                f"Fonte do Website: {valid_url}\n"
                f"Título da Página: {title}\n"
                f"----------------------------------------\n"
                f"{content}"
            )

            logger.info(f"[WebPageExtractor] Conteúdo extraído com sucesso de '{valid_url}' ({len(full_document_text)} caracteres).")

            return {
                'ok': True,
                'url': valid_url,
                'domain': parsed.netloc,
                'title': title,
                'meta_description': meta_desc,
                'content': full_document_text,
                'length_chars': len(full_document_text)
            }

        except requests.exceptions.Timeout:
            logger.warning(f"[WebPageExtractor] Timeout ao tentar conectar em '{valid_url}'.")
            return {'ok': False, 'error': f'Tempo limite esgotado ({timeout}s) ao conectar no site.'}
        except requests.exceptions.SSLError:
            logger.warning(f"[WebPageExtractor] Erro de certificado SSL em '{valid_url}'.")
            return {'ok': False, 'error': 'Erro de certificado SSL seguro no website informado.'}
        except requests.exceptions.ConnectionError:
            logger.warning(f"[WebPageExtractor] Falha de conexão com '{valid_url}'.")
            return {'ok': False, 'error': 'Não foi possível estabelecer conexão com o endereço informado. Verifique se o site está online.'}
        except Exception as e:
            logger.error(f"[WebPageExtractor] Exceção inesperada ao extrair '{valid_url}': {e}", exc_info=True)
            return {'ok': False, 'error': f'Erro ao processar página: {str(e)}'}
