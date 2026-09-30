import logging
from functools import wraps
from flask import flash, redirect, url_for, request, jsonify

logger = logging.getLogger(__name__)

SECTORS = {
    'gestao_clientes': {
        'name': 'Gestão de Clientes',
        'icon': 'fa-users',
        'description': 'CRM Core: Leads, Funil Kanban, Prospecção e Agendamentos',
        'modules': {
            'funnel': {'name': 'Funil Kanban de Vendas', 'default': True, 'desc': 'Pipelines e estágios visuais'},
            'clients': {'name': 'Cadastro de Clientes', 'default': True, 'desc': 'Gestão de contatos e histórico'},
            'prospecting': {'name': 'Prospecção Google Maps', 'default': True, 'desc': 'Scraper ativo e enriquecimento'},
            'tasks': {'name': 'Tarefas e Lembretes', 'default': True, 'desc': 'Compromissos por cliente'},
            'gamification': {'name': 'Gamificação e Ranking', 'default': True, 'desc': 'Pontuação e métricas'}
        }
    },
    'ia_automacao': {
        'name': 'IA e Automação',
        'icon': 'fa-robot',
        'description': 'Motores de Inteligência Artificial local, RAG e Resposta Automática',
        'modules': {
            'llm_providers': {'name': 'Provedores LLM', 'default': True, 'desc': 'Ollama, Gemini, DeepSeek'},
            'rag_engine': {'name': 'Engine RAG (Base de Conhecimento)', 'default': True, 'desc': 'Busca semântica no ChromaDB'},
            'tf_engine': {'name': 'TensorFlow Neural Engine', 'default': True, 'desc': 'Rede neural local Keras/C++'},
            'auto_responder': {'name': 'Auto-Responder WhatsApp', 'default': True, 'desc': 'Bot inteligente com debounce'},
            'faq_miner': {'name': 'FAQ Miner e Ingestor', 'default': True, 'desc': 'Mineração de perguntas frequentes'}
        }
    },
    'configuracao': {
        'name': 'Configuração',
        'icon': 'fa-gear',
        'description': 'Parâmetros do sistema, segurança, anti-ban e customização',
        'modules': {
            'system_settings': {'name': 'Configurações Globais', 'default': True, 'desc': 'Gerais da aplicação'},
            'antiban': {'name': 'Sistema Anti-Ban WhatsApp', 'default': True, 'desc': 'Limites e delays de disparo'},
            'backups': {'name': 'Gerenciador de Backups', 'default': True, 'desc': 'Backup automático e restore'},
            'ui_theme': {'name': 'Personalização Visual / Temas', 'default': True, 'desc': 'Cores HSL e temas CSS'},
            'audit_logs': {'name': 'Logs e Auditoria', 'default': True, 'desc': 'Histórico de ações do sistema'}
        }
    },
    'integracoes': {
        'name': 'Integrações',
        'icon': 'fa-plug',
        'description': 'Gateways de mensageria, ERPs e Webhooks',
        'modules': {
            'waha': {'name': 'Gateway WAHA WhatsApp', 'default': True, 'desc': 'API HTTP para WhatsApp'},
            'waha_bulk': {'name': 'Disparo em Lote WAHA', 'default': True, 'desc': 'Campanhas em segundo plano, filtros de leads e anti-ban'},
            'bling': {'name': 'ERP Bling', 'default': True, 'desc': 'Sincronização de pedidos e produtos'},
            'webhooks': {'name': 'Webhooks Customizados', 'default': True, 'desc': 'Recebimento e disparo de eventos'}
        }
    },
    'motor_plugins': {
        'name': 'Plugins',
        'icon': 'fa-puzzle-piece',
        'description': 'Motor Extensível e Plugins de Terceiros',
        'modules': {
            'plugin_registry': {'name': 'Gerenciador de Plugins', 'default': True, 'desc': 'Plugins ativos e ciclo de vida'},
            'event_bus': {'name': 'Barramento de Eventos', 'default': True, 'desc': 'Hooks e escutadores'},
            'hook_manager': {'name': 'Injetor de Hooks UI', 'default': True, 'desc': 'Pontos de extensão visual'}
        }
    }
}

class ModuleRegistry:
    @classmethod
    def get_setting_key(cls, sector: str, module: str) -> str:
        return f"module_{sector}_{module}_enabled"

    @classmethod
    def is_module_enabled(cls, module_path: str) -> bool:
        """
        Verifica se um módulo está ativado.
        module_path pode ser:
        - "prospecting" (busca simples por nome do módulo)
        - "gestao_clientes.prospecting" (busca por setor.modulo)
        """
        if not module_path:
            return True

        if '.' in module_path:
            sector, module = module_path.split('.', 1)
        else:
            module = module_path
            sector = None
            for sec_key, sec_data in SECTORS.items():
                if module in sec_data['modules']:
                    sector = sec_key
                    break

        if not sector:
            return True

        setting_key = cls.get_setting_key(sector, module)
        
        try:
            from app.models import Setting
            val = Setting.get_val(setting_key, 'true')
            return str(val).strip().lower() in ['true', '1', 'yes', 'sim']
        except Exception as e:
            logger.debug(f"[ModuleRegistry] Erro ao consultar flag {setting_key}: {e}")
            return True

    @classmethod
    def get_all_sectors(cls):
        """Retorna todos os setores e módulos com seus status atuais."""
        result = {}
        for sector_key, sector_data in SECTORS.items():
            sec_dict = {
                'name': sector_data['name'],
                'icon': sector_data['icon'],
                'description': sector_data['description'],
                'modules': {}
            }
            for mod_key, mod_data in sector_data['modules'].items():
                is_enabled = cls.is_module_enabled(f"{sector_key}.{mod_key}")
                sec_dict['modules'][mod_key] = {
                    'name': mod_data['name'],
                    'desc': mod_data['desc'],
                    'enabled': is_enabled,
                    'key': cls.get_setting_key(sector_key, mod_key)
                }
            result[sector_key] = sec_dict
        return result

def is_module_enabled(module_path: str) -> bool:
    return ModuleRegistry.is_module_enabled(module_path)

def requires_module(module_path: str):
    """Decorator para rotas HTTP que exigem determinado módulo ativo."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not is_module_enabled(module_path):
                msg = f"O módulo '{module_path}' está desativado no momento."
                if request.is_json or request.path.startswith('/api/'):
                    return jsonify({'success': False, 'error': msg, 'module_disabled': True}), 403
                flash(msg, 'warning')
                return redirect(url_for('main.index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator
