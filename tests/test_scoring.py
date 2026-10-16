"""Pruebas de la lógica pura (sin FastAPI ni base de datos)."""
import pytest

from app.scoring import Accion, NivelRiesgo, evaluar


def _repartir(total: int, n: int) -> list[int]:
    """Reparte `total` en `n` respuestas de 0 a 3."""
    items = []
    for _ in range(n):
        v = min(3, total)
        items.append(v)
        total -= v
    assert total == 0, "total imposible"
    return items


def phq(total: int) -> list[int]:
    return _repartir(total, 9)  # ítem 9 queda en 0 mientras total <= 24


def gad(total: int) -> list[int]:
    return _repartir(total, 7)


@pytest.mark.parametrize(
    "total, nivel, accion",
    [
        (9, NivelRiesgo.BAJO, Accion.EJERCICIOS),
        (10, NivelRiesgo.MODERADO, Accion.CITA),
        (14, NivelRiesgo.MODERADO, Accion.CITA),
        (15, NivelRiesgo.ALTO, Accion.CITA_PRIORITARIA),
    ],
)
def test_limites_phq9(total, nivel, accion):
    r = evaluar(phq(total), gad(0))
    assert (r.puntaje_phq9, r.nivel, r.accion) == (total, nivel, accion)


@pytest.mark.parametrize(
    "total, nivel",
    [(9, NivelRiesgo.BAJO), (10, NivelRiesgo.MODERADO), (14, NivelRiesgo.MODERADO), (15, NivelRiesgo.ALTO)],
)
def test_limites_gad7(total, nivel):
    r = evaluar(phq(0), gad(total))
    assert (r.puntaje_gad7, r.nivel) == (total, nivel)


def test_criterio_1_phq12_gad6_es_moderado_con_cita():
    r = evaluar(phq(12), gad(6))
    assert r.nivel is NivelRiesgo.MODERADO and r.accion is Accion.CITA


def test_item9_mayor_a_cero_es_critico_aunque_puntaje_sea_bajo():
    r = evaluar([0] * 8 + [1], gad(0))
    assert r.nivel is NivelRiesgo.CRITICO and r.accion is Accion.CRISIS


def test_item9_gana_sobre_puntaje_alto():
    assert evaluar([3] * 9, gad(0)).nivel is NivelRiesgo.CRITICO


def test_puntajes_maximos():
    r = evaluar([3] * 9, [3] * 7)
    assert (r.puntaje_phq9, r.puntaje_gad7) == (27, 21)


@pytest.mark.parametrize(
    "phq9, gad7",
    [([0] * 8, [0] * 7), ([0] * 9, [0] * 6), ([0] * 8 + [4], [0] * 7), ([0] * 8 + [-1], [0] * 7)],
)
def test_respuestas_invalidas(phq9, gad7):
    with pytest.raises(ValueError):
        evaluar(phq9, gad7)
