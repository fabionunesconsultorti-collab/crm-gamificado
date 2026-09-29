import logging
from typing import Dict, Type, Optional
from app import db
from app.models import IntegrationConfig
from app.integrations.base import BaseIntegrationAdapter

logger = logging.getLogger(__name__)

class IntegrationManager:
    """
    Gerenciador Central de Integrações (Registry & Factory pattern).
    Permite registrar, ativar, desativar e invocar adaptadores de forma 100% desacoplada.
    """
    _adapters: Dict[str, Type[BaseIntegrationAdapter]] = {}

    @classmethod
    def register(cls, adapter_cls: Type[BaseIntegrationAdapter]):
        """Registra um novo adaptador de integração."""
        cls._adapters[adapter_cls.provider_name] = adapter_cls
        logger.info(f"[IntegrationManager] Adaptador registrado: '{adapter_cls.provider_name}' ({adapter_cls.display_name})")
        return adapter_cls

    @classmethod
    def get_adapter(cls, provider: str) -> Optional[BaseIntegrationAdapter]:
        """Instancia e retorna o adaptador correspondente ao provider se registrado."""
        adapter_cls = cls._adapters.get(provider)
        if not adapter_cls:
            return None
        return adapter_cls()

    @classmethod
    def get_all_integrations(cls) -> list:
        """Retorna a lista de todas as integrações registradas e seus status atuais no banco."""
        result = []
        for provider, adapter_cls in cls._adapters.items():
            adapter = adapter_cls()
            config = adapter.get_config()
            result.append({
                'provider': provider,
                'name': adapter.display_name,
                'description': adapter.description,
                'is_active': bool(config.is_active),
                'auth_type': config.auth_type,
                'client_id': config.client_id or '',
                'has_client_secret': bool(config.client_secret),
                'has_api_key': bool(config.api_key),
                'has_access_token': bool(config.access_token),
                'token_expires_at': config.token_expires_at.strftime('%Y-%m-%d %H:%M:%S') if config.token_expires_at else None,
                'settings': config.get_settings(),
                'updated_at': config.updated_at.strftime('%d/%m/%Y %H:%M') if config.updated_at else ''
            })
        return result

    @classmethod
    def toggle_integration(cls, provider: str, active: bool) -> dict:
        """Ativa ou desativa uma integração no banco de dados."""
        adapter = cls.get_adapter(provider)
        if not adapter:
            return {'success': False, 'message': f'Provedor "{provider}" não encontrado.'}

        config = adapter.get_config()
        config.is_active = bool(active)
        db.session.commit()

        # Executa callback de ativação/inativação no adaptador se existir
        toggle_info = {}
        if hasattr(adapter, 'on_toggle'):
            try:
                toggle_info = adapter.on_toggle(bool(active)) or {}
            except Exception as e:
                logger.error(f"[IntegrationManager] Erro no callback on_toggle para {provider}: {e}")

        status_str = "ativada" if active else "desativada"
        adapter.log('toggle_status', 'info', f'Integração {status_str} via painel administrativo.')
        
        msg = toggle_info.get('message') or f'Integração {adapter.display_name} {status_str} com sucesso.'
        return {
            'success': True,
            'message': msg,
            'is_active': config.is_active
        }

    @classmethod
    def update_config(cls, provider: str, data: dict) -> dict:
        """Atualiza credenciais e parâmetros da integração."""
        adapter = cls.get_adapter(provider)
        if not adapter:
            return {'success': False, 'message': f'Provedor "{provider}" não encontrado.'}

        config = adapter.get_config()

        if 'auth_type' in data:
            config.auth_type = data['auth_type']
        if 'client_id' in data:
            config.client_id = data['client_id'].strip()
        if 'client_secret' in data and data['client_secret']:
            config.client_secret = data['client_secret'].strip()
        if 'api_key' in data and data['api_key']:
            config.api_key = data['api_key'].strip()
        if 'access_token' in data and data['access_token']:
            config.access_token = data['access_token'].strip()

        # Atualiza o JSON de configurações personalizadas
        current_settings = config.get_settings()
        if 'settings' in data and isinstance(data['settings'], dict):
            current_settings.update(data['settings'])
            config.set_settings(current_settings)

        db.session.commit()
        adapter.log('update_config', 'info', 'Configurações atualizadas com sucesso.')
        return {'success': True, 'message': f'Configurações de {adapter.display_name} atualizadas.'}
