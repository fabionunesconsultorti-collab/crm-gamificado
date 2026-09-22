import socket
import logging
import re

logger = logging.getLogger(__name__)

def get_connected_ip():
    """
    Detecta e retorna dinamicamente o endereço IP da máquina na interface de rede conectada.
    Se não houver rede externa/ativa, retorna '127.0.0.1'.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Usa rota de saída UDP (não envia tráfego real nem precisa de resposta)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def get_default_waha_url(port=3000):
    """
    Retorna a URL padrão do WAHA baseada no IP conectado atual.
    """
    ip = get_connected_ip()
    return f"http://{ip}:{port}"

def resolve_instance_api_url(api_url, target_port=3000):
    """
    Garante que URLs contendo IPs estáticos antigos/inválidos (como 192.168.1.44)
    sejam resolvidas para o IP correto conectado atualmente.
    """
    if not api_url:
        return get_default_waha_url(target_port)
        
    current_ip = get_connected_ip()
    
    # Se contiver explicitamente o IP inválido 192.168.1.44, substitui pelo IP conectado
    if '192.168.1.44' in api_url:
        return api_url.replace('192.168.1.44', current_ip)
        
    return api_url
