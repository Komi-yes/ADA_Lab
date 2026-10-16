"""Autenticación con JWT (el campo `sub` es el id del usuario)."""
from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)


def usuario_autenticado(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> str:
    error = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "No pudimos confirmar quién eres. Inicia sesión otra vez.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if cred is None:
        raise error
    try:
        datos = jwt.decode(
            cred.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},  # un token sin vencimiento no sirve
        )
    except jwt.PyJWTError:
        raise error from None
    sub = datos.get("sub")
    if not isinstance(sub, str) or not sub:
        raise error
    return sub
