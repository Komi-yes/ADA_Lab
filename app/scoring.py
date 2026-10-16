"""Lógica pura de puntaje y clasificación de riesgo (PHQ-9 y GAD-7).

Este módulo NO depende de FastAPI, de la base de datos ni de logging, así que
se puede probar y reutilizar de forma aislada.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

PHQ9_ITEMS = 9
GAD7_ITEMS = 7
VALOR_MIN, VALOR_MAX = 0, 3
UMBRAL_MODERADO = 10
UMBRAL_ALTO = 15
# Índice (base 0) del ítem 9 del PHQ-9: ideas de autolesión.
INDICE_ITEM_AUTOLESION = 8


class NivelRiesgo(str, Enum):
    BAJO = "bajo"
    MODERADO = "moderado"
    ALTO = "alto"
    CRITICO = "crítico"


class Accion(str, Enum):
    EJERCICIOS = "ejercicios"
    CITA = "cita"
    CITA_PRIORITARIA = "cita_prioritaria"
    CRISIS = "crisis"


# Regla 5: acción asociada a cada nivel de riesgo.
ACCION_POR_NIVEL: dict[NivelRiesgo, Accion] = {
    NivelRiesgo.BAJO: Accion.EJERCICIOS,
    NivelRiesgo.MODERADO: Accion.CITA,
    NivelRiesgo.ALTO: Accion.CITA_PRIORITARIA,
    NivelRiesgo.CRITICO: Accion.CRISIS,
}


@dataclass(frozen=True)
class Resultado:
    puntaje_phq9: int
    puntaje_gad7: int
    nivel: NivelRiesgo
    accion: Accion


def validar_respuestas(respuestas: Sequence[int], cantidad: int, nombre: str) -> None:
    """Lanza ValueError si la lista no tiene `cantidad` enteros entre 0 y 3."""
    if len(respuestas) != cantidad:
        raise ValueError(f"El cuestionario {nombre} debe tener {cantidad} respuestas.")
    for valor in respuestas:
        # bool es subclase de int; lo rechazamos explícitamente.
        if isinstance(valor, bool) or not isinstance(valor, int) or not VALOR_MIN <= valor <= VALOR_MAX:
            raise ValueError(f"Cada respuesta de {nombre} debe ser un número entero de 0 a 3.")


def calcular_puntaje(respuestas: Sequence[int]) -> int:
    """Suma simple de las respuestas."""
    return sum(respuestas)


def clasificar_riesgo(phq9: Sequence[int], gad7: Sequence[int]) -> NivelRiesgo:
    """Aplica las reglas 1 a 4. El orden importa: crítico > alto > moderado > bajo."""
    mayor = max(calcular_puntaje(phq9), calcular_puntaje(gad7))
    if phq9[INDICE_ITEM_AUTOLESION] > 0:  # Regla 3: sin importar el puntaje total
        return NivelRiesgo.CRITICO
    if mayor >= UMBRAL_ALTO:  # Regla 2
        return NivelRiesgo.ALTO
    if mayor >= UMBRAL_MODERADO:  # Regla 1
        return NivelRiesgo.MODERADO
    return NivelRiesgo.BAJO  # Regla 4


def evaluar(phq9: Sequence[int], gad7: Sequence[int]) -> Resultado:
    """Valida, calcula puntajes, clasifica el riesgo y decide la acción."""
    validar_respuestas(phq9, PHQ9_ITEMS, "PHQ-9")
    validar_respuestas(gad7, GAD7_ITEMS, "GAD-7")
    nivel = clasificar_riesgo(phq9, gad7)
    return Resultado(calcular_puntaje(phq9), calcular_puntaje(gad7), nivel, ACCION_POR_NIVEL[nivel])
