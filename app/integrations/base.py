from abc import ABC, abstractmethod
import logging
from app import db
from app.models import IntegrationConfig, IntegrationLog

logger = logging.getLogger(__name__)

class BaseIntegrationAdapter(ABC):
    """
    Classe base para todos os adaptadores de integração no CRM.
    Garante interface padronizada e desacoplada.
    """

    provider_name: str = "base"
    display_name: str = "Base Integration"
    description: str = "Descrição da integração"

    def get_config(self) -> IntegrationConfig:
        """Obtém ou cria a configuração da integração no banco de dados."""
        config = IntegrationConfig.query.filter_by(provider=self.provider_name).first()
        if not config:
            config = IntegrationConfig(
                provider=self.provider_name,
                name=self.display_name,
                is_active=False,
                settings_json='{}'
            )
            db.session.add(config)
            db.session.commit()
        return config

    def is_enabled(self) -> bool:
        """Verifica se a integração está ativa."""
        config = self.get_config()
        return bool(config and config.is_active)

    def log(self, action: str, status: str = 'info', details: str = ''):
        """Registra logs da integração no banco de dados."""
        try:
            log_entry = IntegrationLog(
                provider=self.provider_name,
                action=action,
                status=status,
                details=str(details)
            )
            db.session.add(log_entry)
            db.session.commit()
        except Exception as e:
            logger.error(f"[IntegrationLog] Erro ao gravar log para {self.provider_name}: {e}")

    @abstractmethod
    def test_connection(self) -> dict:
        """Valida credenciais e conectividade com a API externa."""
        pass

    @abstractmethod
    def sync_clients_inbound(self, limit: int = 100) -> dict:
        """Importa contatos da API externa para o CRM."""
        pass

    @abstractmethod
    def sync_clients_outbound(self, client_id: int = None) -> dict:
        """Exporta contatos do CRM para a API externa."""
        pass

    @abstractmethod
    def fetch_sales_reports(self, start_date=None, end_date=None) -> dict:
        """Obtém dados de vendas/pedidos para relatórios."""
        pass
