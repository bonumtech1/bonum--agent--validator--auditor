# Coaching Audit & Validation Agent

Servicio en **FastAPI** que valida y audita las sesiones de coaching de Bonum.
Núcleo **determinístico** (reglas exactas, sin LLM en las decisiones).

## Arquitectura

```
React (front)
   │  crear sesión
   ▼
Servicio de Sesiones (Node)  ──POST /validate-session──►  ESTE SERVICIO (FastAPI)
   │  si approved → persiste                                  │
   │                                                          ├─ consulta disponibilidad/bloqueos
   ▼                                                          │  al Servicio de Calendario (Node + Nylas)
Servicio de Calendario (Node + Nylas) ◄───────────────────────┘
```

- **Validador** (`POST /validate-session`): síncrono. El servicio de sesiones lo
  llama *antes* de persistir; bloquea si hay un hallazgo de severidad alta.
- **Auditor** (`POST /audit-session`): post-creación. Calcula un *score* 0–100
  y la lista de hallazgos de una sesión ya existente.

## Reglas implementadas

| Código | Severidad | Qué verifica |
|---|---|---|
| `INVALID_TIME_RANGE` | alta | fin posterior al inicio |
| `OUTSIDE_AVAILABILITY` | alta | dentro del horario disponible (Nylas) |
| `OVERLAPS_BLOCK` | alta | no choca con bloqueos/vacaciones |
| `SESSION_CONFLICT` | alta | no se solapa con otra sesión |
| `COACH_OVERLOADED` | alta | no excede sesiones/día |
| `DURATION_TOO_SHORT/LONG` | media | duración dentro de rango |
| `INSUFFICIENT_LEAD_TIME` | media | anticipación mínima |
| `INSUFFICIENT_BUFFER` | media | descanso entre sesiones |

Todos los umbrales son configurables por variables de entorno (ver `.env.example`).

## Correr localmente

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # USE_STUB_CLIENTS=true → no necesita los servicios Node
uvicorn app.main:app --reload
```

Probar:

```bash
curl -X POST localhost:8000/validate-session -H 'Content-Type: application/json' -d '{
  "coachId": "coach-1", "clientId": "client-1",
  "startTime": "2026-06-20T10:00:00Z", "endTime": "2026-06-20T11:00:00Z"
}'
```

## Tests

```bash
pytest
```

## Despliegue

Mismo pipeline que `services--sessions` (push → ECR → Lightsail): `develop`→dev,
`main`→prod. Ver **[`docs/DEPLOY.md`](docs/DEPLOY.md)** para prerequisitos (ECR,
Lightsail, GitHub Secrets) y el paso clave de apuntar `AGENT_API` en sesiones a la
URL desplegada. Archivos: `Dockerfile`, `docker-compose.yml`, `.env.dev`/`.env.prod`,
`.github/workflows/{dev,production}.yml`, `task-definition.json`.

## Conectar los servicios reales

Con `USE_STUB_CLIENTS=true` el servicio funciona con datos simulados (coach
disponible 09:00–18:00, sin conflictos). Para conectar los Node reales:

1. Pon `USE_STUB_CLIENTS=false` y configura `CALENDAR_SERVICE_URL` / `SESSIONS_SERVICE_URL`.
2. Ajusta los paths y el parseo del JSON en `app/clients/calendar.py` y
   `app/clients/sessions.py` (marcados con `TODO`).

## Persistencia (MongoDB)

El auditor guarda cada resultado en MongoDB (colección `session_audits`).
Configura `MONGODB_URI` y `MONGODB_DB` en `.env`. Si `MONGODB_URI` queda vacía,
la persistencia se desactiva y el servicio sigue funcionando (no guarda nada).

- `POST /audit-session` → calcula el score **y lo guarda** (upsert por `sessionId`).
- `GET /sessions/{id}/audit` → devuelve la última auditoría guardada (para React).
- `GET /health` → informa `db: connected | disabled`.

## Auditor (sesiones ya creadas)

A diferencia del validador, el auditor **no** usa el endpoint de disponibilidad
(ese excluye el slot de la propia sesión). Reconstruye la ventana laboral del
coach desde `WorkSchedule` (horario local por día) + el **timezone** del coach
(Nexus: `profiles/coach/{id}` → `data.userId.timezone`), y compara cada sesión.

- `POST /audit-session` → audita una sesión y la persiste.
- `POST /audit-coach/{coachId}?future_only=false` → audita TODAS las sesiones del
  coach en lote (trae timezone + horario + sesiones una sola vez), persiste cada
  auditoría, genera alertas y devuelve un resumen (`audited`, `avg_score`, `by_risk`).

**Limitación actual:** los bloqueos/vacaciones (`BlockedSchedule`) requieren auth
(Firebase JWT) y aún no se consumen en el auditor; por ahora solo valida horario
laboral. El validador sí los cubre (vía disponibilidad). Pendiente: token de
servicio para leer bloqueos en el auditor.

## Job programado (monitoreo automático)

Un scheduler (APScheduler) audita a **todos los coaches** cada
`AUDIT_INTERVAL_MINUTES` (default **60**). Arranca con la app si
`SCHEDULER_ENABLED=true`.

- Lista los coaches con sesiones (`GetAllSessions`, paginado).
- Audita cada uno en paralelo (`AUDIT_MAX_CONCURRENCY`, default 5), tolerante a
  fallos (un coach que falle no tumba el barrido).
- Por defecto `AUDIT_FUTURE_ONLY=true`: solo audita sesiones **futuras** (el
  objetivo es vigilar lo recién agendado, no re-auditar el pasado cada hora).
- Coaches sin horario configurado o sin perfil se **omiten** (no se marcan como
  errores ni se les inventan hallazgos).

Control manual:
- `POST /audit/run-all` → dispara el barrido completo ahora.
- `GET /audit/last-run` → resumen del último barrido (programado o manual):
  `{coaches, audited_sessions, high_risk_sessions, coaches_failed}`.

## Auditor de salud de calendario

Detecta coaches cuya configuración rompe el agendamiento (causa común de "errores
con horarios"). Solo usa datos accesibles sin credenciales de Nylas.

| Hallazgo | Severidad | Qué significa |
|---|---|---|
| `PROFILE_NOT_FOUND` | alta | el coach no existe en Nexus (sesiones huérfanas) |
| `MISSING_TIMEZONE` | alta | sin timezone → disponibilidad mal calculada |
| `NO_WORK_SCHEDULE` | alta | no trabaja ningún día → no se le puede agendar |
| `MISCONFIGURED_SCHEDULE` | media | día laborable con horas inválidas (`init>=end`, etc.) |
| `NOT_BOOKABLE` | alta | tiene días laborables pero 0 disponibilidad N días (calendario/timezone roto) |

- `POST /audit/calendar-health/{coachId}` → chequea un coach.
- `POST /audit/calendar-health` → chequea a todos.
- `GET /calendar-health/issues` → coaches con problemas (para el dashboard).
- Se incluye en el barrido programado si `AUDIT_CALENDAR_HEALTH=true`.

**Limitación:** confirmar si un grant de Nylas está vivo/revocado requiere la API
key de Nylas; sin ella, `NOT_BOOKABLE` es la mejor señal indirecta de conexión rota.

## Validación de reagendamiento

Reagendar tiene el mismo riesgo que crear (mover a una hora no disponible). El
endpoint `POST /validate-session` cubre ambos casos. La integración en
`services--sessions` (crear + reagendar) está documentada en
[`docs/INTEGRATION-sessions-service.md`](docs/INTEGRATION-sessions-service.md).

## Centro de Alertas

El auditor genera alertas automáticas (colección `audit_alerts`) cuando una
auditoría cruza un umbral. Determinístico, sin IA.

| Tipo | Cuándo se dispara |
|---|---|
| `LOW_SCORE` | score < `ALERT_LOW_SCORE_THRESHOLD` (default 50) |
| `OUT_OF_HOURS` | la sesión cae fuera del horario laboral del coach |
| `COACH_OVERLOADED` | el coach excede `MAX_SESSIONS_PER_DAY` |
| `SESSION_CONFLICT` | la sesión se solapa con otra |

Las alertas se **deduplican** por `dedup_key` (no se repiten) y conservan su
estado aunque se re-audite.

- `GET /alerts?status=&severity=&coachId=` → lista con filtros.
- `PATCH /alerts/{id}?status=revisada|ignorada|escalada` → cambia el estado.
- `GET /alerts/ui` → **vista HTML** para verlas en el navegador (provisional;
  el dashboard final irá en React).

## Pendiente (próximas fases)

- Auditor programado (job diario) + endpoints de dashboard (`audit_runs`).
- Capa LLM opcional para resúmenes ejecutivos en lenguaje natural.
```
