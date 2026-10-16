# Motor de evaluación de riesgo (C5)

Servicio FastAPI que calcula PHQ-9 y GAD-7, clasifica el riesgo (bajo, moderado, alto, crítico) y sugiere la acción
siguiente. Si el riesgo es crítico llama a `notificar_crisis(usuario_id)` (simula C6, ver `app/crisis.py`).

## Estructura
- `app/scoring.py`: lógica pura de puntajes y reglas (sin FastAPI ni BD).
- `app/service.py`: flujo principal y regla de 14 días.
- `app/main.py`: endpoint `POST /tamizajes` protegido con JWT.
- `app/crypto.py`, `app/db.py`, `app/security.py`, `app/config.py`: cifrado Fernet, SQLite, JWT y entorno.

## Instalación
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # completa C5_FERNET_KEY y C5_JWT_SECRET
```
Generar la clave Fernet: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

## Ejecución
Define las variables de `.env` en tu shell (el servicio las lee del entorno) y luego:
```bash
uvicorn app.main:app --reload
pytest
```
`pytest` ya mide la cobertura y falla si baja de 95 % (ver `pytest.ini`). Para ver el detalle por línea:
```bash
pytest --cov=app --cov-report=term-missing
```

## Ejemplo
El JWT debe llevar `sub` igual al `usuario_id` y estar firmado con `C5_JWT_SECRET` (HS256 por defecto).
```bash
curl -X POST http://localhost:8000/tamizajes \
  -H "Authorization: Bearer <JWT>" -H "Content-Type: application/json" \
  -d '{"usuario_id":"joven-1","phq9":[3,3,3,3,0,0,0,0,0],"gad7":[3,3,0,0,0,0,0]}'
```
Respuesta:
```json
{"puntaje_phq9":12,"puntaje_gad7":6,"nivel_riesgo":"moderado","accion_sugerida":"cita","fecha":"2026-10-15T12:00:00+00:00"}
```
Códigos: `401` sin token válido, `403` token de otro usuario, `409` tamizaje antes de 14 días (salvo si el anterior fue
crítico), `422` respuestas inválidas.

## Qué se guarda y cómo
| Dato | Cómo se guarda |
|---|---|
| Respuestas individuales (PHQ-9 y GAD-7) | **Cifradas** con Fernet (`respuestas_cifradas`) |
| Puntajes, nivel de riesgo, acción, fecha, `usuario_id` | **En claro**, para consultar el histórico |
| `crisis_notificada` | `NULL` si no fue crisis, `true` si C6 recibió el aviso, `false` si quedó pendiente de reintento |

Ni las respuestas ni los puntajes se escriben en los logs.

## Comportamiento importante
- **Arranque:** la app valida las variables de entorno y la clave Fernet; si algo falta o es inválido, no arranca.
- **JWT:** debe incluir `exp` y `sub`; sin ellos responde 401.
- **Regla de 14 días:** la comprobación y el guardado van en la misma transacción (`BEGIN IMMEDIATE` en SQLite), así que dos envíos simultáneos del mismo usuario no pasan los dos.
- **Aviso a C6:** espera como máximo 3 s. Si C6 falla o tarda más, el resultado queda guardado y `crisis_notificada=false`. `service.reintentar_crisis_pendientes` reenvía los pendientes (hay que llamarlo desde un proceso programado). Si C6 tardó pero sí recibió el aviso, el reintento puede duplicarlo: conviene que C6 lo tolere.
- **Base de datos existente:** la columna `crisis_notificada` es nueva; si ya tienes un `c5.db` de antes, bórralo o migra la tabla.
- Las fechas se guardan en UTC y se devuelven con zona (`+00:00`).
- Valores de `nivel_riesgo`: `bajo`, `moderado`, `alto`, `crítico`.
