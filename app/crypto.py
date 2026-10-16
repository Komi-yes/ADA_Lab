"""Cifrado de las respuestas individuales con Fernet."""
from __future__ import annotations

import json
from typing import Sequence

from cryptography.fernet import Fernet


class Cifrador:
    def __init__(self, clave: str) -> None:
        self._fernet = Fernet(clave.encode())

    def cifrar_respuestas(self, phq9: Sequence[int], gad7: Sequence[int]) -> str:
        datos = json.dumps({"phq9": list(phq9), "gad7": list(gad7)})
        return self._fernet.encrypt(datos.encode()).decode()

    def descifrar_respuestas(self, token: str) -> dict[str, list[int]]:
        return json.loads(self._fernet.decrypt(token.encode()))
