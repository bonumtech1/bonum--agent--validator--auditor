"""Cálculo de la ventana de horario laboral del coach en UTC.

El servicio de calendario guarda el horario (`WorkSchedule`) en hora LOCAL del
coach (`HH:mm`) sin la zona horaria; la zona vive en el user service (Nexus).
Aquí replicamos la conversión que hace el calendario: interpretar `InitialDate`/
`EndDate` como hora local del coach y convertir a UTC, para el día de la sesión.

Función pura y determinística (sin red), testeable con cualquier timezone.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.core.models import TimeWindow

# Mapa de WorkSchedule: {"Monday": {"work": bool, "init": "08:00", "end": "17:00"}, ...}
WorkScheduleMap = dict[str, dict]


def _parse_hm(value: str) -> tuple[int, int]:
    h, m = value.split(":")
    return int(h), int(m)


def work_window_for(
    start_utc: datetime, work_schedule: WorkScheduleMap, tz_name: str
) -> list[TimeWindow]:
    """Ventana laboral (en UTC) del coach para el día de `start_utc`.

    Devuelve [] si ese día el coach no trabaja o no hay horario configurado.
    """
    tz = ZoneInfo(tz_name)
    local = start_utc.astimezone(tz)
    day_name = local.strftime("%A")  # Monday, Tuesday, ...

    ws = work_schedule.get(day_name)
    if not ws or not ws.get("work") or not ws.get("init") or not ws.get("end"):
        return []

    sh, sm = _parse_hm(ws["init"])
    eh, em = _parse_hm(ws["end"])
    ws_start = datetime(local.year, local.month, local.day, sh, sm, tzinfo=tz)
    ws_end = datetime(local.year, local.month, local.day, eh, em, tzinfo=tz)
    return [
        TimeWindow(
            start=ws_start.astimezone(timezone.utc),
            end=ws_end.astimezone(timezone.utc),
        )
    ]
