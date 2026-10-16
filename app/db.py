"""Conexión a SQLite y modelo del histórico de tamizajes."""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any, Iterator

from sqlalchemy import Boolean, DateTime, Engine, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


class Tamizaje(Base):
    """Un tamizaje guardado. Las respuestas individuales van cifradas."""

    __tablename__ = "tamizajes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[str] = mapped_column(String(64), index=True)
    fecha: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC, sin zona
    puntaje_phq9: Mapped[int] = mapped_column(Integer)
    puntaje_gad7: Mapped[int] = mapped_column(Integer)
    nivel_riesgo: Mapped[str] = mapped_column(String(16))
    accion: Mapped[str] = mapped_column(String(32))
    respuestas_cifradas: Mapped[str] = mapped_column(Text)
    # None = no aplica (no fue crisis); True = C6 recibió el aviso; False = pendiente de reintento.
    crisis_notificada: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)


def crear_engine(url: str, **kwargs: Any) -> Engine:
    """Crea el engine. En SQLite cada transacción empieza con BEGIN IMMEDIATE.

    Así, la comprobación de los 14 días y el guardado ocurren bajo el mismo
    bloqueo de escritura: dos envíos simultáneos del mismo usuario no pueden
    pasar los dos la comprobación.
    """
    if not url.startswith("sqlite"):
        return create_engine(url, **kwargs)

    kwargs.setdefault("connect_args", {})
    kwargs["connect_args"].setdefault("check_same_thread", False)
    kwargs["connect_args"].setdefault("timeout", 10)  # espera el bloqueo en vez de fallar
    engine = create_engine(url, **kwargs)

    @event.listens_for(engine, "connect")
    def _sin_transaccion_automatica(dbapi_conn: Any, _: Any) -> None:
        dbapi_conn.isolation_level = None  # el driver no abre transacciones por su cuenta

    @event.listens_for(engine, "begin")
    def _begin_immediate(conn: Any) -> None:
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    engine = crear_engine(get_settings().database_url)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with get_session_factory()() as session:
        yield session
