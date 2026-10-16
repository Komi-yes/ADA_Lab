"""Configuración leída de variables de entorno (nunca claves en el código)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from cryptography.fernet import Fernet

# Solo algoritmos simétricos HMAC; evita valores peligrosos como "none".
ALGORITMOS_PERMITIDOS = {"HS256", "HS384", "HS512"}
LARGO_MINIMO_SECRETO = 16


@dataclass(frozen=True)
class Settings:
    fernet_key: str
    jwt_secret: str
    jwt_algorithm: str
    database_url: str


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings(
            fernet_key=os.environ["C5_FERNET_KEY"],
            jwt_secret=os.environ["C5_JWT_SECRET"],
            jwt_algorithm=os.environ.get("C5_JWT_ALGORITHM", "HS256"),
            database_url=os.environ.get("C5_DATABASE_URL", "sqlite:///./c5.db"),
        )
    except KeyError as e:
        raise RuntimeError(f"Falta la variable de entorno {e.args[0]}.") from None


def validar_configuracion() -> Settings:
    """Se llama al arrancar la app: falla pronto y con un mensaje claro."""
    settings = get_settings()
    try:
        Fernet(settings.fernet_key.encode())
    except (ValueError, TypeError):
        raise RuntimeError(
            "C5_FERNET_KEY no es una clave Fernet válida (32 bytes en base64 seguro para URL)."
        ) from None
    if len(settings.jwt_secret) < LARGO_MINIMO_SECRETO:
        raise RuntimeError(f"C5_JWT_SECRET debe tener al menos {LARGO_MINIMO_SECRETO} caracteres.")
    if settings.jwt_algorithm not in ALGORITMOS_PERMITIDOS:
        raise RuntimeError(f"C5_JWT_ALGORITHM debe ser uno de: {', '.join(sorted(ALGORITMOS_PERMITIDOS))}.")
    return settings
