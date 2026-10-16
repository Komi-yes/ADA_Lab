"""Pruebas de configuración, arranque y conexión real a la base."""
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import db as db_mod
from app.config import get_settings, validar_configuracion
from app.main import app


@pytest.fixture(autouse=True)
def limpiar_caches():
    get_settings.cache_clear()
    db_mod.get_session_factory.cache_clear()
    yield
    get_settings.cache_clear()
    db_mod.get_session_factory.cache_clear()


def test_configuracion_valida():
    assert validar_configuracion().jwt_algorithm == "HS256"


@pytest.mark.parametrize("variable", ["C5_FERNET_KEY", "C5_JWT_SECRET"])
def test_falta_variable_da_mensaje_claro(monkeypatch, variable):
    monkeypatch.delenv(variable)
    with pytest.raises(RuntimeError, match=f"Falta la variable de entorno {variable}"):
        validar_configuracion()


def test_clave_fernet_invalida(monkeypatch):
    monkeypatch.setenv("C5_FERNET_KEY", "no-es-una-clave")
    with pytest.raises(RuntimeError, match="clave Fernet válida"):
        validar_configuracion()


def test_secreto_jwt_muy_corto(monkeypatch):
    monkeypatch.setenv("C5_JWT_SECRET", "corto")
    with pytest.raises(RuntimeError, match="al menos"):
        validar_configuracion()


@pytest.mark.parametrize("algoritmo", ["none", "RS256"])
def test_algoritmo_jwt_no_permitido(monkeypatch, algoritmo):
    monkeypatch.setenv("C5_JWT_ALGORITHM", algoritmo)
    with pytest.raises(RuntimeError, match="C5_JWT_ALGORITHM"):
        validar_configuracion()


def test_la_app_no_arranca_con_configuracion_mala(monkeypatch):
    monkeypatch.setenv("C5_FERNET_KEY", "mala")
    with pytest.raises(RuntimeError, match="Fernet"):
        with TestClient(app):
            pass


def test_la_app_arranca_con_configuracion_buena():
    with TestClient(app) as c:
        assert c.get("/nada").status_code == 404


def test_get_db_usa_la_base_configurada(monkeypatch, tmp_path):
    monkeypatch.setenv("C5_DATABASE_URL", f"sqlite:///{tmp_path / 'real.db'}")
    monkeypatch.setenv("C5_FERNET_KEY", Fernet.generate_key().decode())
    gen = db_mod.get_db()
    sesion = next(gen)
    assert sesion.query(db_mod.Tamizaje).count() == 0
    gen.close()
    db_mod.get_session_factory().kw["bind"].dispose()
    assert (tmp_path / "real.db").exists()
