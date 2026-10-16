"""Modelos Pydantic de entrada y salida."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, Field, field_serializer

from app.scoring import Accion, NivelRiesgo

Respuesta = Annotated[int, Field(ge=0, le=3, strict=True)]


class TamizajeEntrada(BaseModel):
    usuario_id: str = Field(min_length=1, max_length=64)
    phq9: list[Respuesta] = Field(min_length=9, max_length=9)
    gad7: list[Respuesta] = Field(min_length=7, max_length=7)


class TamizajeSalida(BaseModel):
    puntaje_phq9: int = Field(ge=0, le=27)
    puntaje_gad7: int = Field(ge=0, le=21)
    nivel_riesgo: NivelRiesgo
    accion_sugerida: Accion
    fecha: datetime

    @field_serializer("fecha")
    def _fecha_utc(self, valor: datetime) -> str:
        """Siempre UTC con zona explícita, p. ej. 2026-10-15T12:00:00+00:00."""
        if valor.tzinfo is None:  # en la base se guarda en UTC sin zona
            valor = valor.replace(tzinfo=timezone.utc)
        return valor.astimezone(timezone.utc).isoformat()
