# Arquitectura — Coaching Audit & Validation Agent

## Visión general

Servicio en **FastAPI** que añade dos capacidades sobre los microservicios de
Bonum, sin reemplazar nada:

- **Validador** (guardia): el servicio de sesiones lo llama **antes** de crear o
  reagendar; bloquea horarios inválidos.
- **Auditor** (observador): revisa **periódicamente** (job horario) las sesiones
  ya creadas y la salud de calendario de los coaches, deja evidencia y genera
  alertas para operaciones.

Todo el núcleo de decisión es **determinístico** (reglas exactas, sin LLM).

```
React (bonum-dashboard)
   │  crear / reagendar
   ▼
Servicio de Sesiones (Node)  ──POST /validate-session──►  ESTE SERVICIO (FastAPI)
   │  approved → persiste                                     │
   │  rejected → 409 con motivos                              ├─► Calendar (Node+Nylas): disponibilidad, WorkSchedule
   ▼                                                          ├─► Sessions (Node): sesiones del coach
Servicio de Calendario (Node + Nylas)                        ├─► Nexus: timezone + providers (grants)
                                                              ├─► Nylas: estado del grant (conexión viva?)
   Job horario (APScheduler) ─► barrido ──────────────────────┘
        audita todo + salud de calendario → MongoDB (auditorías + alertas)
   bonum-dashboard (sección Auditoría) ◄── GET /alerts, /session-audits, /calendar-health/issues
```

## Componentes (código)

| Módulo | Responsabilidad |
|---|---|
| `app/main.py` | App FastAPI, endpoints, CORS, lifespan (Mongo + scheduler) |
| `app/config.py` | Configuración por entorno (`Settings`) |
| `app/core/rules.py` | **Motor de reglas** determinístico (validar/auditar) |
| `app/core/schedule.py` | WorkSchedule (hora local) → ventana UTC (con timezone/DST) |
| `app/core/context.py` | Arma el contexto del coach (validador vs auditor) |
| `app/core/models.py` | Modelos Pydantic |
| `app/clients/calendar.py` | Disponibilidad + WorkSchedule (servicio calendario) |
| `app/clients/sessions.py` | Sesiones del coach + lista de coaches |
| `app/clients/users.py` | Timezone + providers del coach (Nexus) |
| `app/clients/nylas.py` | Estado del grant de Nylas (conexión rota?) |
| `app/auditor/runner.py` | Auditoría por coach / todos + resumen |
| `app/auditor/calendar_health.py` | Chequeos de salud de calendario |
| `app/auditor/scheduler.py` | Job horario (APScheduler) |
| `app/alerts/detector.py` | Deriva alertas de auditorías/salud |
| `app/alerts/view.py` | Vista HTML de alertas |
| `app/db/mongo.py` · `app/db/repository.py` | Persistencia MongoDB |

## Decisión de diseño clave: validador vs auditor

- El **validador** usa el endpoint de **disponibilidad** del calendario, que ya
  descuenta horario + bloqueos + eventos + sesiones existentes. Fuente única de
  verdad; no duplicamos lógica.
- El **auditor** NO puede usar disponibilidad (excluye el slot de la propia
  sesión que audita), así que **reconstruye** la ventana laboral desde
  `WorkSchedule` + el **timezone** del coach (Nexus).

## Datos consumidos de otros servicios

| Dato | Origen | Endpoint |
|---|---|---|
| Disponibilidad (slots libres) | Calendar | `GET /calendarsUnprotected/availability?userid&date` |
| Horario laboral | Calendar | `GET /workscheduleUnprotected/GetByUser?userid` |
| Sesiones del coach | Sessions | `GET /session/coach/{id}` |
| Lista de coaches | Sessions | `GET /session/GetAllSessions` (paginado) |
| Timezone + providers (grant) | Nexus | `GET /profiles/coach/{id}` → `data.userId` |
| Estado del grant | Nylas | `GET /v3/grants/{grantId}` |

## Persistencia (MongoDB)

BD propia `coaching_audit` (separada de la `bonum` de los servicios):

| Colección | Contenido |
|---|---|
| `session_audits` | una auditoría por sesión (score, hallazgos) |
| `audit_alerts` | alertas operativas (con estado mutable) |
| `calendar_health` | salud de calendario por coach |

Mongo es **opcional**: si no conecta, el servicio arranca igual (`db: disabled`)
y el validador sigue funcionando; solo se desactiva la persistencia/auditor.

## Job programado

`APScheduler` corre el barrido cada `AUDIT_INTERVAL_MINUTES` (60). Por defecto
`AUDIT_FUTURE_ONLY=true` (solo sesiones futuras — monitorea lo recién agendado).
Coaches sin horario/perfil se omiten sin romper el barrido.

> Importante: el scheduler corre **en proceso** → desplegar con **1 sola
> instancia / 1 worker** (`--scale 1`). Con réplicas, el barrido se duplicaría.

## Despliegue
AWS Lightsail vía GitHub Actions (`develop`→dev, `main`→prod). Ver
[`DEPLOY.md`](DEPLOY.md). Integración en el servicio de sesiones:
[`INTEGRATION-sessions-service.md`](INTEGRATION-sessions-service.md). Referencia
de endpoints: [`API.md`](API.md).

## Frontend
`bonum-dashboard` → sección **Auditoría** (`/audit`): KPIs, gráficos (sesiones por
riesgo, alertas por tipo, salud de calendario), centro de alertas (cambio de
estado), tabla de auditoría de sesiones y salud de calendario. Consume la API vía
`VITE_API_AUDIT_URL`.
