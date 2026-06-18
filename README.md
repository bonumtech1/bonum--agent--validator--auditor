# Coaching Audit & Validation Agent

Servicio **FastAPI** que valida y audita las sesiones de coaching de Bonum y la
salud de calendario de los coaches. Núcleo **determinístico** (sin LLM en las
decisiones).

- **Validador** (`POST /validate-session`): el servicio de sesiones lo llama
  **antes** de crear/reagendar; bloquea si el horario es inválido.
- **Auditor** (job horario): revisa sesiones ya creadas y la configuración de
  calendario de cada coach; genera alertas y un score por sesión.

## Documentación

| Doc | Contenido |
|---|---|
| [`docs/API.md`](docs/API.md) | Referencia de todos los endpoints + catálogo de hallazgos/alertas |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Arquitectura, componentes, datos consumidos, persistencia |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | Despliegue en AWS Lightsail (CI/CD) |
| [`docs/INTEGRATION-sessions-service.md`](docs/INTEGRATION-sessions-service.md) | Cómo integrar el validador en `services--sessions` |

## Correr localmente

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # USE_STUB_CLIENTS=true → no necesita los servicios Node
uvicorn app.main:app --reload
# http://localhost:8000/docs   (Swagger)
# http://localhost:8000/alerts/ui
```

Probar el validador:
```bash
curl -X POST localhost:8000/validate-session -H 'x-app-id: coaching' \
  -H 'Content-Type: application/json' -d '{
  "coachId":"c1","clientId":"cl1",
  "startTime":"2026-06-22T10:00:00Z","endTime":"2026-06-22T11:00:00Z" }'
```

## Tests
```bash
pytest        # 28 tests (reglas, schedule, alertas, salud de calendario, cliente)
```

## Configuración (variables de entorno)

Ver [`.env.example`](.env.example). Las más relevantes:

| Variable | Default | Para qué |
|---|---|---|
| `USE_STUB_CLIENTS` | `true` | `false` para usar los servicios Node reales |
| `APP_ID` | `coaching` | header `x-app-id` (`coaching`/`mentoring`) |
| `CALENDAR_SERVICE_URL` / `SESSIONS_SERVICE_URL` / `NEXUS_API_URL` | — | servicios consumidos |
| `NYLAS_API_KEY` / `NYLAS_API_URI` | — | detectar conexiones de calendario rotas (secreto) |
| `MONGODB_URI` / `MONGODB_DB` | — / `coaching_audit` | persistencia (opcional) |
| `SCHEDULER_ENABLED` | `true` | activar el job horario |
| `AUDIT_INTERVAL_MINUTES` | `60` | frecuencia del barrido |
| `AUDIT_FUTURE_ONLY` | `true` | auditar solo sesiones futuras |
| `AUDIT_CALENDAR_HEALTH` | `true` | incluir salud de calendario en el barrido |
| `MIN/MAX_SESSION_MINUTES`, `MAX_SESSIONS_PER_DAY`, `BUFFER_MINUTES`, `MIN_LEAD_TIME_MINUTES`, `ALERT_LOW_SCORE_THRESHOLD` | — | umbrales de reglas/alertas |

## Estructura
```
app/
  main.py            # FastAPI: endpoints, CORS, lifespan (Mongo + scheduler)
  config.py          # Settings (env)
  core/              # rules.py (motor), schedule.py (tz), context.py, models.py
  clients/           # calendar, sessions, users (nexus), nylas
  auditor/           # runner, calendar_health, scheduler
  alerts/            # detector, view (HTML)
  db/                # mongo, repository
tests/               # pruebas del núcleo determinístico
docs/                # API, ARCHITECTURE, DEPLOY, INTEGRATION
```

## Estado
Desplegado en AWS Lightsail (dev) con CI/CD. Validador integrado en
`services--sessions` (dev). Dashboard: sección **Auditoría** en `bonum-dashboard`.

> Seguridad: rotar la credencial de Mongo inicial y usar un usuario dedicado a
> `coaching_audit` (no `god`).
