"""Flujo principal: validar -> puntuar -> clasificar -> guardar -> disparar acción."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import scoring
from app.crisis import TIEMPO_LIMITE_CRISIS_S, Notificador
from app.crypto import Cifrador
from app.db import Tamizaje

logger = logging.getLogger("c5.service")

DIAS_ENTRE_TAMIZAJES = 14  # Regla 6

# Hilos donde corre la llamada a C6, para poder ponerle tiempo límite.
_EJECUTOR_C6 = ThreadPoolExecutor(max_workers=8, thread_name_prefix="c6")


class TamizajeMuyReciente(Exception):
    """El usuario todavía no puede repetir el tamizaje."""

    def __init__(self, dias_restantes: int) -> None:
        self.dias_restantes = dias_restantes


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _verificar_espera(db: Session, usuario_id: str, ahora: datetime) -> None:
    """Regla 6: 14 días entre tamizajes, salvo que el anterior fuera crítico.

    Debe ejecutarse en la misma transacción que el guardado (ver db.crear_engine).
    """
    ultimo = db.scalars(
        select(Tamizaje).where(Tamizaje.usuario_id == usuario_id).order_by(Tamizaje.fecha.desc()).limit(1)
    ).first()
    if ultimo is None or ultimo.nivel_riesgo == scoring.NivelRiesgo.CRITICO.value:
        return
    faltante = ultimo.fecha + timedelta(days=DIAS_ENTRE_TAMIZAJES) - ahora
    if faltante > timedelta(0):
        raise TamizajeMuyReciente(faltante.days + 1)


def _avisar_c6(notificar: Notificador, usuario_id: str, limite: float) -> bool:
    """Llama a C6 esperando como máximo `limite` segundos. True si avisó bien."""
    futuro = _EJECUTOR_C6.submit(notificar, usuario_id)
    try:
        futuro.result(timeout=limite)
        return True
    except TimeoutError:
        logger.error("C6 no respondió a tiempo; el aviso de crisis queda pendiente.")
    except Exception:  # noqa: BLE001 - C6 caído no debe tumbar la respuesta
        logger.error("Falló el aviso de crisis a C6; queda pendiente.")
    return False


def registrar_tamizaje(
    db: Session,
    usuario_id: str,
    phq9: Sequence[int],
    gad7: Sequence[int],
    cifrador: Cifrador,
    notificar: Notificador,
    ahora: datetime | None = None,
    limite_crisis: float = TIEMPO_LIMITE_CRISIS_S,
) -> Tamizaje:
    ahora = ahora or ahora_utc()
    resultado = scoring.evaluar(phq9, gad7)  # valida y calcula
    es_crisis = resultado.accion is scoring.Accion.CRISIS

    _verificar_espera(db, usuario_id, ahora)
    tamizaje = Tamizaje(
        usuario_id=usuario_id,
        fecha=ahora,
        puntaje_phq9=resultado.puntaje_phq9,
        puntaje_gad7=resultado.puntaje_gad7,
        nivel_riesgo=resultado.nivel.value,
        accion=resultado.accion.value,
        respuestas_cifradas=cifrador.cifrar_respuestas(phq9, gad7),
        crisis_notificada=False if es_crisis else None,
    )
    db.add(tamizaje)
    db.commit()  # primero se guarda: el resultado no se pierde si C6 falla

    if es_crisis and _avisar_c6(notificar, usuario_id, limite_crisis):
        tamizaje.crisis_notificada = True
        db.commit()
    return tamizaje


def reintentar_crisis_pendientes(
    db: Session, notificar: Notificador, limite_crisis: float = TIEMPO_LIMITE_CRISIS_S
) -> int:
    """Reintenta los avisos a C6 que fallaron. Devuelve cuántos se enviaron bien."""
    pendientes = db.scalars(select(Tamizaje).where(Tamizaje.crisis_notificada.is_(False))).all()
    enviados = 0
    for t in pendientes:
        if _avisar_c6(notificar, t.usuario_id, limite_crisis):
            t.crisis_notificada = True
            enviados += 1
    db.commit()
    return enviados
