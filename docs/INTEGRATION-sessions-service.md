# Integración del validador en `services--sessions`

El validador (`POST /validate-session` de este servicio FastAPI) debe llamarse
**antes de persistir** una sesión, tanto al **crear** como al **reagendar**.
Esto es el guardia del lado del servidor: garantiza que no se guarde una sesión
fuera del horario del coach, aunque el frontend lo permita o alguien llame la API
directo.

> El mismo endpoint sirve para crear y reagendar: reagendar = validar la hora nueva.

## 1. Variable de entorno

En el `.env` de `services--sessions`:

```
AGENT_API=https://<url-del-servicio-de-agentes>
```

## 2. Servicio de validación (nuevo archivo)

`src/domain/services/validation.service.ts` — espejo de `calendar.service.ts`:

```typescript
import { axios } from '../../infrastructure/core/httpcall'; // o el helper http que usen

const AGENT_API = process.env.AGENT_API as string;

export interface ValidationResult {
  approved: boolean;
  risk: 'low' | 'medium' | 'high';
  reasons: string[];
}

export class ValidationService {
  async validateSession(
    params: { coachId: string; clientId: string; startTime: string; endTime: string },
    appId: string,
  ): Promise<ValidationResult> {
    const { data } = await axios.post(`${AGENT_API}/validate-session`, params, {
      headers: { 'x-app-id': appId },
      timeout: 5000,
    });
    return data;
  }
}
```

## 3. Helper de duración (1 hora)

```typescript
import { DateTime } from 'luxon'; // ya lo usan

const addOneHour = (isoDate: string): string =>
  DateTime.fromISO(isoDate, { zone: 'utc' }).plus({ hours: 1 }).toISO();
```

## 4. Wiring en `SessionController`

### En `Add()` (crear) — antes de persistir (~línea 1117, junto a la validación de "1 sesión por día")

```typescript
const validation = await this.validationService.validateSession(
  {
    coachId: entity.coach,
    clientId: entity.coachee,
    startTime: entity.date,            // ISO en UTC
    endTime: addOneHour(entity.date),  // duración fija 1h
  },
  appId,
);

if (!validation.approved) {
  return res.status(409).json({
    success: false,
    message: 'Horario no válido para el coach',
    reasons: validation.reasons,       // p.ej. ["La sesión cae fuera del horario disponible del coach."]
  });
}
// ...continúa el flujo normal de creación
```

### En `Reschedule()` y `Reschedule2()` — antes de actualizar la fecha (~líneas 2164 y 2312)

```typescript
const newDate = entity.date ?? data.date; // la hora destino del reagendamiento
const validation = await this.validationService.validateSession(
  {
    coachId: previousSession.coach,
    clientId: previousSession.coachee,
    startTime: newDate,
    endTime: addOneHour(newDate),
  },
  appId,
);

if (!validation.approved) {
  return res.status(409).json({
    success: false,
    message: 'No se puede reagendar a ese horario',
    reasons: validation.reasons,
  });
}
// ...continúa el reagendamiento
```

## 5. Notas

- **Fail-open vs fail-closed:** decидир qué pasa si el servicio de agentes no
  responde. Recomendado para empezar: si la llamada falla (timeout/red), **dejar
  pasar** la creación (fail-open) y loguear, para no bloquear el negocio por una
  caída del auditor. Cuando haya confianza, cambiar a fail-closed.
- El validador llama internamente al servicio de calendario; el servicio de
  sesiones **no** necesita llamar a calendario para validar.
- `x-app-id` debe propagarse (`coaching` | `mentoring`), igual que en el resto
  de llamadas entre servicios.
```
