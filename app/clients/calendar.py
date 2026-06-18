"""Cliente al servicio de Calendario (Node + Nylas).

Define la interfaz que el motor de reglas necesita. Hay dos implementaciones:

  • CalendarClient      → llama al servicio real por HTTP.
  • StubCalendarClient  → devuelve datos simulados (sin red), para desarrollo y tests.

Cuando tengas los contratos reales de los endpoints Node, ajusta los paths y el
parseo en CalendarClient. La interfaz (CalendarClientBase) no debería cambiar.
"""

from abc import ABC, abstractmethod
from datetime import datetime, time, timedelta, timezone

import httpx

from app.config import Settings
from app.core.models import TimeWindow


class CalendarClientBase(ABC):
    @abstractmethod
    async def get_availability(
        self, coach_id: str, start: datetime, end: datetime
    ) -> list[TimeWindow]:
        """Ventanas en las que el coach está disponible (horario laboral / Nylas)."""

    @abstractmethod
    async def get_blocks(
        self, coach_id: str, start: datetime, end: datetime
    ) -> list[TimeWindow]:
        """Ventanas bloqueadas: vacaciones, reuniones internas, eventos ocupados."""

    @abstractmethod
    async def get_work_schedule(self, coach_id: str) -> dict:
        """Horario laboral del coach por día (para el AUDITOR).

        Devuelve {"Monday": {"work": bool, "init": "HH:MM", "end": "HH:MM"}, ...}.
        """


class CalendarClient(CalendarClientBase):
    """Implementación real contra services--calendar.

    `get_availability` consume el endpoint canónico de slots libres
    (`/calendarsUnprotected/availability`), que YA descuenta horario laboral,
    bloqueos, eventos de Nylas y sesiones existentes. Por eso es la única fuente
    de verdad para el validador y `get_blocks` devuelve [] (no duplicamos lógica:
    los bloqueos ya están restados de la disponibilidad).

    Devuelve un slot de 1 hora por cada timestamp que retorna el servicio
    (el calendario trabaja en intervalos fijos de 1 hora).
    """

    SLOT_MINUTES = 60

    def __init__(self, base_url: str, timeout: float, app_id: str):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._headers = {"x-app-id": app_id}

    async def get_availability(
        self, coach_id: str, start: datetime, end: datetime
    ) -> list[TimeWindow]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base_url}/calendarsUnprotected/availability",
                params={"userid": coach_id, "date": start.isoformat()},
                headers=self._headers,
            )
            resp.raise_for_status()
            payload = resp.json()

        slots = payload.get("data", []) if isinstance(payload, dict) else payload
        windows = []
        for iso in slots:
            slot_start = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            windows.append(
                TimeWindow(start=slot_start, end=slot_start + timedelta(minutes=self.SLOT_MINUTES))
            )
        return windows

    async def get_blocks(
        self, coach_id: str, start: datetime, end: datetime
    ) -> list[TimeWindow]:
        # Los bloqueos ya están descontados de la disponibilidad (ver docstring).
        return []

    async def get_work_schedule(self, coach_id: str) -> dict:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base_url}/workscheduleUnprotected/GetByUser",
                params={"userid": coach_id},
                headers=self._headers,
            )
            resp.raise_for_status()
            payload = resp.json()
        data = payload.get("data", []) if isinstance(payload, dict) else payload
        return {
            item["Day"]: {
                "work": bool(item.get("Work")),
                "init": item.get("InitialDate"),
                "end": item.get("EndDate"),
            }
            for item in data
            if item.get("Day")
        }


class StubCalendarClient(CalendarClientBase):
    """Datos simulados: coach disponible de 09:00 a 18:00 UTC, sin bloqueos."""

    async def get_availability(
        self, coach_id: str, start: datetime, end: datetime
    ) -> list[TimeWindow]:
        day = start.date()
        tz = start.tzinfo or timezone.utc
        return [
            TimeWindow(
                start=datetime.combine(day, time(9, 0), tzinfo=tz),
                end=datetime.combine(day, time(18, 0), tzinfo=tz),
            )
        ]

    async def get_blocks(
        self, coach_id: str, start: datetime, end: datetime
    ) -> list[TimeWindow]:
        return []

    async def get_work_schedule(self, coach_id: str) -> dict:
        # Coach simulado: trabaja todos los días 09:00–18:00.
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        return {d: {"work": True, "init": "09:00", "end": "18:00"} for d in days}


def build_calendar_client(cfg: Settings) -> CalendarClientBase:
    if cfg.use_stub_clients:
        return StubCalendarClient()
    return CalendarClient(cfg.calendar_service_url, cfg.http_timeout_seconds, cfg.app_id)
