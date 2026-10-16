"""Interfaz hacia el componente C6 (atención de crisis). Aquí solo se simula."""
from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger("c5.crisis")

Notificador = Callable[[str], None]

# Máximo que esperamos a C6 antes de responder al usuario (criterio de aceptación 2).
TIEMPO_LIMITE_CRISIS_S = 3.0


def notificar_crisis(usuario_id: str) -> None:
    """Simula la llamada a C6. Se registra solo que hubo aviso, sin datos clínicos."""
    logger.warning("Se notificó una crisis a C6 para el usuario %s", usuario_id)


def get_notificador() -> Notificador:
    """Dependencia de FastAPI: permite cambiar el notificador en las pruebas."""
    return notificar_crisis
