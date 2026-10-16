import os
import time

from cryptography.fernet import Fernet

# Las variables deben existir antes de importar la app.
os.environ["C5_FERNET_KEY"] = Fernet.generate_key().decode()
os.environ["C5_JWT_SECRET"] = "secreto-de-pruebas-con-longitud-suficiente"

from unittest.mock import MagicMock

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.crisis import get_notificador
from app.db import Base, crear_engine, get_db
from app.main import app


def crear_token(payload: dict, secreto: str | None = None) -> str:
    return jwt.encode(payload, secreto or os.environ["C5_JWT_SECRET"], algorithm="HS256")


def token_para(usuario_id: str, **cambios) -> dict[str, str]:
    """Cabecera con un JWT válido. Con `exp=None` o `sub=None` se quita ese campo."""
    payload = {"sub": usuario_id, "exp": int(time.time()) + 3600, **cambios}
    payload = {k: v for k, v in payload.items() if v is not None}
    return {"Authorization": f"Bearer {crear_token(payload)}"}


def _montar_client(factory: sessionmaker, notificador) -> TestClient:
    def _db():
        with factory() as s:
            yield s

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_notificador] = lambda: notificador
    return TestClient(app)


@pytest.fixture()
def session_factory():
    engine = crear_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture()
def session_factory_archivo(tmp_path):
    """Base real en archivo, con conexiones independientes por hilo."""
    engine = crear_engine(f"sqlite:///{tmp_path / 'prueba.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture()
def notificador():
    return MagicMock()


@pytest.fixture()
def client(session_factory, notificador):
    yield _montar_client(session_factory, notificador)
    app.dependency_overrides.clear()


@pytest.fixture()
def client_archivo(session_factory_archivo, notificador):
    yield _montar_client(session_factory_archivo, notificador)
    app.dependency_overrides.clear()
