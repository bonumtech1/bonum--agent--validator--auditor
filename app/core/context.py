"""Arma el CoachContext consultando los servicios de calendario y sesiones.

Esta es la única capa que mezcla red + dominio: trae los datos crudos de los
clientes y los empaqueta en el CoachContext que el motor de reglas consume.
Las tres consultas son independientes, así que van en paralelo.
"""

import asyncio
from datetime import datetime

from app.clients.calendar import CalendarClientBase
from app.clients.sessions import SessionsClientBase
from app.clients.users import UserClientBase
from app.core.models import CoachContext, SessionRequest
from app.core.schedule import work_window_for


async def build_coach_context(
    s: SessionRequest,
    calendar: CalendarClientBase,
    sessions: SessionsClientBase,
) -> CoachContext:
    """Contexto para el VALIDADOR (pre-creación).

    Usa la disponibilidad canónica del calendario, que ya descuenta horario,
    bloqueos, eventos y sesiones existentes.
    """
    start, end = s.start_time, s.end_time
    availability, blocks, existing = await asyncio.gather(
        calendar.get_availability(s.coach_id, start, end),
        calendar.get_blocks(s.coach_id, start, end),
        sessions.get_sessions(s.coach_id, start, end),
    )
    return CoachContext(
        coach_id=s.coach_id,
        availability=availability,
        blocks=blocks,
        existing_sessions=existing,
    )


async def build_audit_context(
    s: SessionRequest,
    calendar: CalendarClientBase,
    sessions: SessionsClientBase,
    users: UserClientBase,
) -> CoachContext:
    """Contexto para el AUDITOR (sesión ya creada).

    No usa la disponibilidad (excluiría el slot de la propia sesión).
    Reconstruye la ventana laboral desde WorkSchedule + timezone del coach.
    """
    tz, work_schedule, existing = await asyncio.gather(
        users.get_timezone(s.coach_id),
        calendar.get_work_schedule(s.coach_id),
        sessions.get_sessions(s.coach_id, s.start_time, s.end_time),
    )
    window = work_window_for(s.start_time, work_schedule, tz)
    return CoachContext(
        coach_id=s.coach_id,
        availability=window,
        blocks=[],
        existing_sessions=existing,
    )
