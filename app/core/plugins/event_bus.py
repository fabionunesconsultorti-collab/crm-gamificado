import logging
from typing import Callable, Dict, List, Any

logger = logging.getLogger(__name__)

class EventBus:
    """
    Barramento Central de Eventos Pub/Sub.
    Permite desacoplar módulos e permitir que plugins escutem e reajam a eventos do CRM.
    """
    _listeners: Dict[str, List[Callable]] = {}

    @classmethod
    def subscribe(cls, event_name: str, callback: Callable):
        """Inscreve uma função callback para escutar um determinado evento."""
        if event_name not in cls._listeners:
            cls._listeners[event_name] = []
        if callback not in cls._listeners[event_name]:
            cls._listeners[event_name].append(callback)
            logger.debug(f"[EventBus] Callback '{callback.__name__}' inscrito no evento '{event_name}'.")

    @classmethod
    def unsubscribe(cls, event_name: str, callback: Callable):
        """Remove a inscrição de um callback de um determinado evento."""
        if event_name in cls._listeners and callback in cls._listeners[event_name]:
            cls._listeners[event_name].remove(callback)
            logger.debug(f"[EventBus] Callback '{callback.__name__}' removido do evento '{event_name}'.")

    @classmethod
    def publish(cls, event_name: str, payload: Any = None) -> List[Any]:
        """Dispara um evento e executa de forma síncrona/segura todos os escutadores inscritos."""
        results = []
        callbacks = cls._listeners.get(event_name, [])
        for callback in callbacks:
            try:
                res = callback(payload) if payload is not None else callback()
                results.append(res)
            except Exception as e:
                logger.error(f"[EventBus] Erro ao executar callback '{callback.__name__}' para o evento '{event_name}': {e}", exc_info=True)
        return results

    @classmethod
    def clear_all(cls):
        """Limpa todos os listeners (útil para testes unitários e recarregamento)."""
        cls._listeners = {}
