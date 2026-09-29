import os
from app.models import Setting

class AIPluginManager:
    """
    Gerenciador Central da Arquitetura de Plugins de Inteligência Artificial:
    Permite ativar, desativar e alternar de forma totalmente independente cada provedor de IA:
    - Ollama (Docker Local)
    - Google Gemini (Cloud API)
    - DeepSeek (Cloud API)
    - TensorFlow (Redes Neurais Locais em C++ / Keras)
    """

    @classmethod
    def get_plugin_states(cls):
        """Retorna o estado de cada plugin (Ativado/Desativado), status de conexão e prioridades."""
        settings = {s.key: s.value for s in Setting.query.all()}

        global_enabled = str(settings.get('ai_enabled', 'true')).strip().lower() in ['true', '1', 'yes', 'sim']
        
        ollama_enabled = str(settings.get('ai_plugin_ollama_enabled', 'true')).strip().lower() in ['true', '1', 'yes', 'sim']
        gemini_enabled = str(settings.get('ai_plugin_gemini_enabled', 'true')).strip().lower() in ['true', '1', 'yes', 'sim']
        deepseek_enabled = str(settings.get('ai_plugin_deepseek_enabled', 'false')).strip().lower() in ['true', '1', 'yes', 'sim']
        tf_enabled = str(settings.get('ai_plugin_tensorflow_enabled', 'true')).strip().lower() in ['true', '1', 'yes', 'sim']

        primary = settings.get('ai_provider', 'ollama')
        api_key = settings.get('ai_api_key', '')

        # Verifica conectividade do Ollama
        from app.utils.ai_handler import AIHandler
        ollama_info = AIHandler.get_available_models()

        # Telemetria do TensorFlow
        from app.utils.tf_engine import TensorFlowEngine
        tf_info = TensorFlowEngine.get_status()

        return {
            'global_ai_enabled': global_enabled,
            'primary_provider': primary,
            'plugins': {
                'ollama': {
                    'name': '🦙 Ollama (Docker Local)',
                    'enabled': ollama_enabled,
                    'online': ollama_info.get('online', False),
                    'models': ollama_info.get('models', []),
                    'is_primary': primary == 'ollama',
                    'badge': 'Gratuito & Ilimitado'
                },
                'google': {
                    'name': '♊ Google Gemini (Cloud API)',
                    'enabled': gemini_enabled,
                    'configured': bool(api_key),
                    'is_primary': primary == 'google' or primary == 'gemini',
                    'badge': 'Nuvem Ultra Rápida'
                },
                'deepseek': {
                    'name': '🐳 DeepSeek (Cloud API)',
                    'enabled': deepseek_enabled,
                    'configured': bool(api_key),
                    'is_primary': primary == 'deepseek',
                    'badge': 'Alta Raciocínio'
                },
                'tensorflow': {
                    'name': '🧠 TensorFlow (Rede Neural Nativa)',
                    'enabled': tf_enabled,
                    'online': True,
                    'version': tf_info.get('version'),
                    'backend': tf_info.get('backend'),
                    'device': tf_info.get('device'),
                    'is_primary': primary == 'tensorflow',
                    'badge': 'Local Keras / C++'
                }
            }
        }

    @classmethod
    def is_plugin_active(cls, plugin_name):
        """Verifica se um plugin específico está ativado no sistema."""
        states = cls.get_plugin_states()
        if not states['global_ai_enabled']:
            return False
        
        plugin_data = states['plugins'].get(plugin_name, {})
        return plugin_data.get('enabled', False)
