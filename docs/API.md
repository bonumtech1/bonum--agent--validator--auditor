# API — Coaching Audit & Validation Agent

Servicio FastAPI que **valida** (antes de crear/reagendar) y **audita** (después)
las sesiones de coaching de Bonum, más la **salud de calendario** de los coaches.

- **Base URL (dev):** `https://container-services-agent-validator-auditor.tclik5ai2vodi.us-east-1.cs.amazonlightsail.com`
- **Docs interactivas:** `GET /docs` (Swagger)
- **Header:** `x-app-id: coaching | mentoring` (requerido en los endpoints que consultan calendar/sessions/nexus; opcional en los de solo-lectura de Mongo).
- **Fechas:** ISO 8601 con zona horaria (UTC). Ej: `2026-06-22T09:00:00Z`.

---

## Índice

| Método | Ruta | Para qué |
|---|---|---|
| GET | `/health` | Estado del servicio + BD |
| POST | `/validate-session` | **Validar** un horario (crear/reagendar) |
| POST | `/audit-session` | Auditar una sesión y persistirla |
| GET | `/sessions/{id}/audit` | Auditoría guardada de una sesión |
| GET | `/session-audits` | Listar auditorías de sesión |
| POST | `/audit-coach/{coachId}` | Auditar todas las sesiones de un coach |
| POST | `/audit/calendar-health/{coachId}` | Salud de calendario de un coach |
| POST | `/audit/calendar-health` | Salud de calendario de todos |
| GET | `/calendar-health/issues` | Coaches con problemas de calendario |
| POST | `/audit/run-all` | Barrido completo (sesiones + calendario) |
| GET | `/audit/last-run` | Resumen del último barrido |
| GET | `/alerts` | Listar alertas (con filtros) |
| PATCH | `/alerts/{id}` | Cambiar estado de una alerta |
| GET | `/alerts/ui` | Vista HTML de alertas |

---

## Salud

### `GET /health`
```json
{ "status": "ok", "db": "connected" }
```
`db`: `connected` | `disabled` (sin `MONGODB_URI` o Mongo inaccesible — el
servicio sigue arriba; el validador no necesita BD).

---

## Validador (síncrono — lo llama el servicio de sesiones)

### `POST /validate-session`
Valida que el horario sea agendable. Úsalo **antes** de crear o reagendar.

**Headers:** `x-app-id`
**Body:**
```json
{
  "coachId": "64b863b8fa41fd0321c4b2ef",
  "clientId": "64c1475ba53b56252e1de662",
  "startTime": "2026-06-22T09:00:00Z",
  "endTime": "2026-06-22T10:00:00Z"
}
```
**Respuesta:**
```json
{ "approved": true, "risk": "low", "reasons": [], "findings": [] }
```
o
```json
{
  "approved": false,
  "risk": "high",
  "reasons": ["La sesión cae fuera del horario disponible del coach."],
  "findings": [{ "code": "OUTSIDE_AVAILABILITY", "severity": "high", "message": "...", "points": 40 }]
}
```
Bloquea (`approved:false`) ante cualquier hallazgo de severidad **alta**.
Internamente consulta la **disponibilidad real** del servicio de calendario.

---

## Auditor de sesiones (post-creación)

### `POST /audit-session`
Audita una sesión ya creada, **persiste** el resultado y genera alertas.

**Headers:** `x-app-id` · **Body:** igual que `/validate-session` + `sessionId`.
**Respuesta** (`AuditResult`):
```json
{ "session_id": "abc", "score": 60, "risk": "high",
  "findings": [{ "code": "OUTSIDE_AVAILABILITY", "severity": "high", "message": "...", "points": 40 }] }
```

### `GET /sessions/{session_id}/audit`
Última auditoría guardada de una sesión. `404` si no existe; `503` si BD desactivada.

### `GET /session-audits`
Lista auditorías de sesión (recientes primero). **Query:** `coachId`, `risk` (opcionales).
```json
[ { "session_id": "abc", "coach_id": "...", "start_time": "...", "end_time": "...",
    "score": 100, "risk": "low", "findings": [], "created_at": "..." } ]
```

### `POST /audit-coach/{coachId}`
Audita **todas** las sesiones de un coach. **Query:** `future_only` (bool, default `false`).
```json
{ "audited": 18, "avg_score": 60.0, "by_risk": {"low":0,"medium":0,"high":18},
  "sessions": [ { "session_id":"...", "score":60, "risk":"high", "findings":["OUTSIDE_AVAILABILITY"] } ] }
```

---

## Salud de calendario

### `POST /audit/calendar-health/{coachId}`
Chequea la configuración de calendario de un coach (timezone, horario, agendable, conexión Nylas).
```json
{ "coach_id": "...", "healthy": false,
  "findings": [{ "code": "NO_WORK_SCHEDULE", "severity": "high", "message": "..." }] }
```

### `POST /audit/calendar-health`
Lo mismo para **todos** los coaches.
```json
{ "ran_at":"...", "coaches":55, "unhealthy":47,
  "issues":[{"coach_id":"...","ok":false,"healthy":false,"issues":["NO_WORK_SCHEDULE"]}],
  "coaches_failed":[] }
```

### `GET /calendar-health/issues`
Coaches con problemas detectados (para el dashboard). `503` si BD desactivada.
```json
[ { "id":"coachId", "coach_id":"...", "healthy":false,
    "findings":[{"code":"NO_CALENDAR_CONNECTED","severity":"high","message":"..."}], "checked_at":"..." } ]
```

---

## Barrido completo / Job programado

### `POST /audit/run-all`
Ejecuta el barrido completo (auditar sesiones de todos + salud de calendario de
todos). Es lo mismo que corre el **job horario**. Persiste y genera alertas.
```json
{ "ran_at":"...", "coaches":55, "audited_sessions":2, "high_risk_sessions":0,
  "coaches_failed":[], "calendar_health": { "unhealthy":47, "coaches":55 } }
```

### `GET /audit/last-run`
Resumen del último barrido (programado o manual). Si nunca corrió:
`{ "status": "sin barridos todavía" }`.

---

## Alertas

### `GET /alerts`
Lista alertas (recientes primero). **Query:** `status`, `severity`, `coachId`.
```json
[ { "id":"NO_WORK_SCHEDULE:coachX", "type":"NO_WORK_SCHEDULE", "severity":"high",
    "title":"Problema de calendario", "description":"...", "coach_id":"coachX",
    "session_id":null, "status":"nueva", "created_at":"...", "updated_at":"..." } ]
```

### `PATCH /alerts/{id}`
Cambia el estado. **Query:** `status` = `revisada | ignorada | escalada | nueva`.
```json
{ "id": "NO_WORK_SCHEDULE:coachX", "status": "revisada" }
```

### `GET /alerts/ui`
Vista HTML simple de las alertas (provisional; el dashboard final es React).

---

## Catálogo de hallazgos y alertas

### Hallazgos de sesión (validador/auditor)
| Código | Severidad | Resta | Qué detecta |
|---|---|---|---|
| `INVALID_TIME_RANGE` | alta | 100 | fin ≤ inicio |
| `OUTSIDE_AVAILABILITY` | alta | 40 | fuera del horario disponible |
| `OVERLAPS_BLOCK` | alta | 40 | choca con bloqueo |
| `SESSION_CONFLICT` | alta | 30 | se solapa con otra sesión |
| `COACH_OVERLOADED` | alta | 15 | excede sesiones/día |
| `DURATION_TOO_SHORT/LONG` | media | 15 | duración fuera de rango |
| `INSUFFICIENT_LEAD_TIME` | media | 10 | poca anticipación (solo validador) |
| `INSUFFICIENT_BUFFER` | media | 10 | poco descanso entre sesiones |

### Hallazgos de salud de calendario
| Código | Severidad | Qué detecta |
|---|---|---|
| `PROFILE_NOT_FOUND` | alta | coach sin perfil en Nexus (huérfano) |
| `MISSING_TIMEZONE` | alta | sin timezone → disponibilidad mal calculada |
| `NO_WORK_SCHEDULE` | alta | sin horario → no se le puede agendar |
| `MISCONFIGURED_SCHEDULE` | media | horario con horas inválidas |
| `NO_CALENDAR_CONNECTED` | alta | sin calendario conectado (sin providers) |
| `BROKEN_CALENDAR_CONNECTION` | alta | grant de Nylas caído/expirado |
| `NOT_BOOKABLE` | alta | días laborables pero 0 disponibilidad |

### Tipos de alerta
`LOW_SCORE` (score < umbral), `OUT_OF_HOURS`, `SESSION_CONFLICT`,
`COACH_OVERLOADED`, y los códigos de salud de calendario de arriba.
Estados: `nueva` → `revisada` | `ignorada` | `escalada`.

---

## Scoring
`score = max(0, 100 - Σ puntos_de_hallazgos)`. Riesgo: `high` si hay algún
hallazgo alto, `medium` si hay medio, `low` si no hay.
