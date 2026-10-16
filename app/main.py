"""API FastAPI del Motor de evaluación de riesgo (C5)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings, get_settings, validar_configuracion
from app.crisis import Notificador, get_notificador
from app.crypto import Cifrador
from app.db import get_db
from app.schemas import TamizajeEntrada, TamizajeSalida
from app.scoring import Accion, NivelRiesgo
from app.security import usuario_autenticado
from app.service import TamizajeMuyReciente, registrar_tamizaje

logger = logging.getLogger("c5.api")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    validar_configuracion()  # si falta algo, la app no arranca
    yield


app = FastAPI(title="Motor de evaluación de riesgo (C5)", lifespan=lifespan)

# Mensajes en español para errores que genera el framework (los nuestros ya vienen en español).
MENSAJES_HTTP = {
    404: "No encontramos esa página. Revisa la dirección e inténtalo otra vez.",
    405: "Esa acción no se puede hacer en esta dirección.",
}
MENSAJE_500 = "Algo salió mal de nuestro lado, no es tu culpa. Inténtalo de nuevo en unos minutos."
MENSAJE_422_GENERAL = "Algo de lo que enviaste no está bien. Revísalo e inténtalo de nuevo."


def _mensaje_validacion(error: dict) -> str:
    """Elige el mensaje según el campo con problema. Nunca incluye el valor enviado."""
    loc = error.get("loc", ())
    if error.get("type") == "json_invalid":
        return "No pudimos leer lo que enviaste. Revisa que el mensaje esté bien escrito."
    if "usuario_id" in loc:
        return "Falta tu identificador de usuario o no es válido."
    if "phq9" in loc:
        return "Revisa el cuestionario PHQ-9: deben ser 9 respuestas y cada una un número entero de 0 a 3."
    if "gad7" in loc:
        return "Revisa el cuestionario GAD-7: deben ser 7 respuestas y cada una un número entero de 0 a 3."
    return MENSAJE_422_GENERAL


@app.exception_handler(RequestValidationError)
async def errores_de_validacion(_: Request, exc: RequestValidationError) -> JSONResponse:
    mensajes = list(dict.fromkeys(_mensaje_validacion(e) for e in exc.errors()))  # sin repetir
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": " ".join(mensajes)}
    )


@app.exception_handler(StarletteHTTPException)
async def errores_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    detalle = MENSAJES_HTTP.get(exc.status_code, exc.detail)
    return JSONResponse({"detail": detalle}, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(Exception)
async def error_inesperado(_: Request, exc: Exception) -> JSONResponse:
    # Solo el tipo del error: así nunca se cuela un dato del usuario en los logs.
    logger.error("Error inesperado (%s)", type(exc).__name__)
    return JSONResponse({"detail": MENSAJE_500}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@app.post("/tamizajes", response_model=TamizajeSalida)
def crear_tamizaje(
    datos: TamizajeEntrada,
    usuario_token: str = Depends(usuario_autenticado),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    notificar: Notificador = Depends(get_notificador),
) -> TamizajeSalida:
    if datos.usuario_id != usuario_token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo puedes enviar tus propias respuestas.")
    try:
        t = registrar_tamizaje(db, datos.usuario_id, datos.phq9, datos.gad7, Cifrador(settings.fernet_key), notificar)
    except TamizajeMuyReciente as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Ya hiciste el cuestionario hace poco. Podrás hacerlo de nuevo en {e.dias_restantes} día(s).",
        ) from None
    return TamizajeSalida(
        puntaje_phq9=t.puntaje_phq9,
        puntaje_gad7=t.puntaje_gad7,
        nivel_riesgo=NivelRiesgo(t.nivel_riesgo),
        accion_sugerida=Accion(t.accion),
        fecha=t.fecha,
    )
