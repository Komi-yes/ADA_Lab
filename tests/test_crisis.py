"""Pruebas del aviso a C6 en la capa de servicio (sin pasar por HTTP)."""
import logging
import threading
import time
from unittest.mock import MagicMock

from app.config import get_settings
from app.crisis import get_notificador, notificar_crisis
from app.crypto import Cifrador
from app.db import Tamizaje
from app.service import registrar_tamizaje, reintentar_crisis_pendientes

PHQ_CRITICO = [0] * 8 + [1]
GAD_0 = [0] * 7


def _registrar(db, notificar, usuario="u1", phq9=PHQ_CRITICO, limite=0.2):
    cifrador = Cifrador(get_settings().fernet_key)
    return registrar_tamizaje(db, usuario, phq9, GAD_0, cifrador, notificar, limite_crisis=limite)


def test_c6_lento_se_corta_por_tiempo_limite(session_factory):
    liberar = threading.Event()
    with session_factory() as db:
        inicio = time.perf_counter()
        t = _registrar(db, lambda _u: liberar.wait(10), limite=0.2)
        liberar.set()
        assert time.perf_counter() - inicio < 2
        assert t.crisis_notificada is False


def test_c6_caido_deja_pendiente(session_factory):
    with session_factory() as db:
        assert _registrar(db, MagicMock(side_effect=RuntimeError("caído"))).crisis_notificada is False


def test_c6_ok_marca_notificada(session_factory):
    with session_factory() as db:
        assert _registrar(db, MagicMock()).crisis_notificada is True


def test_sin_crisis_no_avisa_ni_marca(session_factory):
    notificar = MagicMock()
    with session_factory() as db:
        t = _registrar(db, notificar, phq9=[0] * 9)
        assert t.crisis_notificada is None
    notificar.assert_not_called()


def test_reintento_envia_solo_los_pendientes(session_factory):
    with session_factory() as db:
        _registrar(db, MagicMock(side_effect=RuntimeError("caído")), usuario="a")
        _registrar(db, MagicMock(), usuario="b")  # este sí llegó
        nuevo = MagicMock()
        assert reintentar_crisis_pendientes(db, nuevo, limite_crisis=0.2) == 1
        nuevo.assert_called_once_with("a")
        assert {t.usuario_id: t.crisis_notificada for t in db.query(Tamizaje)} == {"a": True, "b": True}
        assert reintentar_crisis_pendientes(db, nuevo) == 0  # ya no queda nada pendiente


def test_reintento_que_vuelve_a_fallar_sigue_pendiente(session_factory):
    with session_factory() as db:
        _registrar(db, MagicMock(side_effect=RuntimeError("caído")))
        assert reintentar_crisis_pendientes(db, MagicMock(side_effect=RuntimeError("caído"))) == 0
        assert db.query(Tamizaje).one().crisis_notificada is False


def test_notificar_crisis_simulado_registra_solo_el_id(caplog):
    with caplog.at_level(logging.DEBUG):
        notificar_crisis("joven-9")
    assert "joven-9" in caplog.text
    assert get_notificador() is notificar_crisis
