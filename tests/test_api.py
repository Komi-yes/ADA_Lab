"""Pruebas de los criterios de aceptación y de los RNF a través de la API."""
import logging
import threading
import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.crisis import get_notificador
from app.crypto import Cifrador
from app.db import Tamizaje, get_db
from app.main import app
from app.service import ahora_utc
from tests.conftest import crear_token, token_para

USER = "joven-1"
PHQ_12 = [3, 3, 3, 3, 0, 0, 0, 0, 0]  # suma 12
GAD_6 = [3, 3, 0, 0, 0, 0, 0]  # suma 6
PHQ_0, GAD_0 = [0] * 9, [0] * 7
PHQ_CRITICO = [0] * 8 + [1]


def cuerpo(phq9, gad7, usuario=USER):
    return {"usuario_id": usuario, "phq9": phq9, "gad7": gad7}


# --- Criterios de aceptación -------------------------------------------------

def test_criterio_1_moderado_y_cita(client):
    r = client.post("/tamizajes", json=cuerpo(PHQ_12, GAD_6), headers=token_para(USER))
    assert r.status_code == 200
    j = r.json()
    assert (j["puntaje_phq9"], j["puntaje_gad7"]) == (12, 6)
    assert j["nivel_riesgo"] == "moderado" and j["accion_sugerida"] == "cita"
    assert j["fecha"]


def test_criterio_2_critico_llama_a_c6_en_menos_de_3s(client, notificador):
    inicio = time.perf_counter()
    r = client.post("/tamizajes", json=cuerpo(PHQ_CRITICO, GAD_0), headers=token_para(USER))
    assert time.perf_counter() - inicio < 3
    assert r.json()["nivel_riesgo"] == "crítico" and r.json()["accion_sugerida"] == "crisis"
    notificador.assert_called_once_with(USER)


def test_criterio_3_segundo_tamizaje_antes_de_14_dias_da_409(client):
    h = token_para(USER)
    assert client.post("/tamizajes", json=cuerpo(PHQ_12, GAD_6), headers=h).status_code == 200
    r = client.post("/tamizajes", json=cuerpo(PHQ_12, GAD_6), headers=h)
    assert r.status_code == 409
    assert "hace poco" in r.json()["detail"]


# --- Regla de los 14 días ----------------------------------------------------

def test_tras_critico_se_puede_repetir_de_inmediato(client):
    h = token_para(USER)
    assert client.post("/tamizajes", json=cuerpo([0] * 8 + [2], GAD_0), headers=h).status_code == 200
    assert client.post("/tamizajes", json=cuerpo(PHQ_0, GAD_0), headers=h).status_code == 200


def _fila_previa(fecha):
    return Tamizaje(usuario_id=USER, fecha=fecha, puntaje_phq9=0, puntaje_gad7=0,
                    nivel_riesgo="bajo", accion="ejercicios", respuestas_cifradas="x")


def test_pasados_14_dias_se_permite(client, session_factory):
    with session_factory() as s:
        s.add(_fila_previa(ahora_utc() - timedelta(days=14, minutes=1)))
        s.commit()
    assert client.post("/tamizajes", json=cuerpo(PHQ_0, GAD_0), headers=token_para(USER)).status_code == 200


def test_a_13_dias_sigue_bloqueado(client, session_factory):
    with session_factory() as s:
        s.add(_fila_previa(ahora_utc() - timedelta(days=13)))
        s.commit()
    assert client.post("/tamizajes", json=cuerpo(PHQ_0, GAD_0), headers=token_para(USER)).status_code == 409


def test_envios_simultaneos_solo_uno_pasa(client_archivo, session_factory_archivo):
    """Varios hilos del mismo usuario a la vez: uno recibe 200 y el resto 409."""
    hilos_n = 6
    barrera = threading.Barrier(hilos_n)
    codigos: list[int] = []

    def enviar():
        barrera.wait()  # todos disparan al mismo tiempo
        r = client_archivo.post("/tamizajes", json=cuerpo(PHQ_0, GAD_0), headers=token_para(USER))
        codigos.append(r.status_code)

    hilos = [threading.Thread(target=enviar) for _ in range(hilos_n)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]

    assert sorted(codigos) == [200] + [409] * (hilos_n - 1)
    with session_factory_archivo() as s:
        assert s.query(Tamizaje).count() == 1


# --- Salida ------------------------------------------------------------------

def test_fecha_en_utc_con_zona(client):
    r = client.post("/tamizajes", json=cuerpo(PHQ_0, GAD_0), headers=token_para(USER))
    fecha = r.json()["fecha"]
    assert fecha.endswith("+00:00")
    assert datetime.fromisoformat(fecha).utcoffset() == timedelta(0)


# --- Autenticación -----------------------------------------------------------

def test_sin_token_da_401(client):
    assert client.post("/tamizajes", json=cuerpo(PHQ_0, GAD_0)).status_code == 401


@pytest.mark.parametrize(
    "cabecera",
    [
        {"Authorization": "Bearer esto-no-es-un-jwt"},
        token_para(USER, exp=int(time.time()) - 10),  # expirado
        token_para(USER, exp=None),  # sin exp
        token_para(USER, sub=None),  # sin sub
        token_para(USER, sub=123),  # sub no es texto
        {"Authorization": f"Bearer {crear_token({'sub': USER, 'exp': int(time.time()) + 600}, 'otra-clave-distinta-con-32-caracteres-o-mas')}"},
    ],
    ids=["basura", "expirado", "sin_exp", "sin_sub", "sub_numerico", "firma_mala"],
)
def test_token_invalido_da_401_en_espanol(client, cabecera):
    r = client.post("/tamizajes", json=cuerpo(PHQ_0, GAD_0), headers=cabecera)
    assert r.status_code == 401
    assert "Inicia sesión" in r.json()["detail"]


def test_token_de_otro_usuario_da_403(client):
    r = client.post("/tamizajes", json=cuerpo(PHQ_0, GAD_0), headers=token_para("otro"))
    assert r.status_code == 403


# --- Validación de entradas (422) -------------------------------------------

@pytest.mark.parametrize(
    "phq9, gad7",
    [
        ([0] * 8, GAD_0),  # PHQ-9 corto
        ([0] * 10, GAD_0),  # PHQ-9 largo
        ([0] * 8 + [4], GAD_0),  # fuera de rango
        ([0] * 8 + [-1], GAD_0),  # negativo
        ([0] * 8 + [1.5], GAD_0),  # decimal
        ([0] * 8 + [1.0], GAD_0),  # decimal "redondo"
        ([0] * 8 + ["SECRETO"], GAD_0),  # texto
        ([0] * 8 + ["1"], GAD_0),  # número como texto
        ([0] * 8 + [True], GAD_0),  # booleano
        ([0] * 8 + [None], GAD_0),  # nulo
    ],
)
def test_phq9_invalido_da_422_sin_eco_del_valor(client, phq9, gad7):
    r = client.post("/tamizajes", json=cuerpo(phq9, gad7), headers=token_para(USER))
    assert r.status_code == 422
    assert "PHQ-9" in r.json()["detail"]
    assert "SECRETO" not in r.text


@pytest.mark.parametrize("gad7", [[0] * 6, [0] * 8, [0] * 6 + [9], [0] * 6 + [0.5]], ids=["corto", "largo", "rango", "decimal"])
def test_gad7_invalido_nombra_el_gad7(client, gad7):
    r = client.post("/tamizajes", json=cuerpo(PHQ_0, gad7), headers=token_para(USER))
    assert r.status_code == 422
    assert "GAD-7" in r.json()["detail"] and "PHQ-9" not in r.json()["detail"]


def test_usuario_id_vacio_nombra_al_usuario(client):
    r = client.post("/tamizajes", json=cuerpo(PHQ_0, GAD_0, usuario=""), headers=token_para(USER))
    assert r.status_code == 422
    assert "identificador de usuario" in r.json()["detail"]


def test_json_roto_da_422_claro(client):
    r = client.post("/tamizajes", content="{esto no es json", headers={**token_para(USER), "content-type": "application/json"})
    assert r.status_code == 422
    assert "No pudimos leer" in r.json()["detail"]


def test_cuerpo_vacio_da_422(client):
    r = client.post("/tamizajes", json={}, headers=token_para(USER))
    assert r.status_code == 422


def test_422_con_varios_errores_junta_mensajes_sin_repetir(client):
    r = client.post("/tamizajes", json=cuerpo([9] * 9, [9] * 7, usuario=""), headers=token_para(USER))
    detalle = r.json()["detail"]
    assert detalle.count("PHQ-9") == 1 and "GAD-7" in detalle and "identificador" in detalle


def test_cuerpo_con_forma_incorrecta_usa_mensaje_general(client):
    r = client.post("/tamizajes", json=[1, 2], headers=token_para(USER))
    assert r.status_code == 422 and "Revísalo" in r.json()["detail"]


# --- Errores del framework en español ---------------------------------------

def test_404_en_espanol(client):
    r = client.get("/nada")
    assert r.status_code == 404 and "No encontramos" in r.json()["detail"]


def test_405_en_espanol(client):
    r = client.get("/tamizajes")
    assert r.status_code == 405 and "no se puede" in r.json()["detail"]


def test_500_en_espanol_y_sin_datos_en_logs(session_factory, caplog):
    def _db_roto():
        raise RuntimeError("DATO-SENSIBLE-123")
        yield  # pragma: no cover

    app.dependency_overrides[get_db] = _db_roto
    try:
        c = TestClient(app, raise_server_exceptions=False)
        with caplog.at_level(logging.DEBUG):
            r = c.post("/tamizajes", json=cuerpo(PHQ_0, GAD_0), headers=token_para(USER))
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 500
    assert "no es tu culpa" in r.json()["detail"]
    assert "DATO-SENSIBLE-123" not in caplog.text and "RuntimeError" in caplog.text


# --- Seguridad de los datos --------------------------------------------------

def test_respuestas_se_guardan_cifradas(client, session_factory):
    client.post("/tamizajes", json=cuerpo(PHQ_12, GAD_6), headers=token_para(USER))
    with session_factory() as s:
        fila = s.query(Tamizaje).one()
    assert "phq9" not in fila.respuestas_cifradas
    claro = Cifrador(get_settings().fernet_key).descifrar_respuestas(fila.respuestas_cifradas)
    assert claro == {"phq9": PHQ_12, "gad7": GAD_6}


def test_logs_no_contienen_respuestas_ni_puntajes(client, caplog):
    with caplog.at_level(logging.DEBUG):
        client.post("/tamizajes", json=cuerpo([2, 2, 2, 2, 2, 2, 2, 2, 1], [3, 1, 2, 3, 1, 2, 3]), headers=token_para(USER))
    texto = caplog.text.lower()
    for prohibido in ("puntaje", "phq", "gad", "[2, 2", "respuestas"):
        assert prohibido not in texto


# --- Aviso a C6 --------------------------------------------------------------

def test_c6_lento_no_bloquea_la_respuesta_mas_de_3s(client, session_factory):
    liberar = threading.Event()
    app.dependency_overrides[get_notificador] = lambda: (lambda _u: liberar.wait(10))
    try:
        inicio = time.perf_counter()
        r = client.post("/tamizajes", json=cuerpo(PHQ_CRITICO, GAD_0), headers=token_para(USER))
        duracion = time.perf_counter() - inicio
    finally:
        liberar.set()
    assert r.status_code == 200 and r.json()["accion_sugerida"] == "crisis"
    assert duracion < 4  # límite de 3 s + margen
    with session_factory() as s:
        assert s.query(Tamizaje).one().crisis_notificada is False


def test_c6_caido_guarda_resultado_y_marca_pendiente(client, notificador, session_factory):
    notificador.side_effect = RuntimeError("C6 caído")
    r = client.post("/tamizajes", json=cuerpo(PHQ_CRITICO, GAD_0), headers=token_para(USER))
    assert r.status_code == 200
    with session_factory() as s:
        assert s.query(Tamizaje).one().crisis_notificada is False


def test_c6_ok_marca_notificada(client, session_factory):
    client.post("/tamizajes", json=cuerpo(PHQ_CRITICO, GAD_0), headers=token_para(USER))
    with session_factory() as s:
        assert s.query(Tamizaje).one().crisis_notificada is True
