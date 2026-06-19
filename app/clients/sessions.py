"""Cliente al servicio de Sesiones (Node).

El modelo real de sesión usa `date` (inicio en UTC) y dura 1 hora fija; los
estados son booleanos (`canceled`, `noShow`, `status`). Adaptamos eso a nuestras
ventanas de tiempo y a `SessionRequest` para auditar.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from app.config import Settings
from app.core.models import TimeWindow

SESSION_MINUTES = 60


@dataclass
class CoachSession:
    """Sesión real, normalizada a inicio/fin UTC."""

    session_id: str
    coach_id: str
    coachee_id: str
    start: datetime
    end: datetime
    canceled: bool


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _coach_id_of(raw: dict) -> str:
    c = raw.get("coach")
    return c.get("_id", "") if isinstance(c, dict) else (c or "")


def _coachee_id_of(raw: dict) -> str:
    c = raw.get("coachee")
    return c.get("_id", "") if isinstance(c, dict) else (c or "")


class SessionsClientBase(ABC):
    @abstractmethod
    async def get_sessions(
        self, coach_id: str, start: datetime, end: datetime
    ) -> list[TimeWindow]:
        """Sesiones (no canceladas) del coach, como ventanas de tiempo."""

    @abstractmethod
    async def list_coach_sessions(self, coach_id: str) -> list[CoachSession]:
        """Todas las sesiones del coach, normalizadas (para auditar en lote)."""

    @abstractmethod
    async def list_coach_ids(self) -> list[str]:
        """IDs distintos de coaches con sesiones (para el job que audita a todos)."""


class SessionsClient(SessionsClientBase):
    def __init__(self, base_url: str, timeout: float, app_id: str):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._headers = {"x-app-id": app_id}

    async def _fetch_raw(self, coach_id: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base_url}/session/coach/{coach_id}", headers=self._headers
            )
            resp.raise_for_status()
            payload = resp.json()
        return payload.get("data", []) if isinstance(payload, dict) else payload

    async def list_coach_sessions(self, coach_id: str) -> list[CoachSession]:
        sessions = []
        for raw in await self._fetch_raw(coach_id):
            if not raw.get("date"):
                continue
            start = _parse_dt(raw["date"])
            sessions.append(
                CoachSession(
                    session_id=str(raw.get("_id", "")),
                    coach_id=_coach_id_of(raw) or coach_id,
                    coachee_id=_coachee_id_of(raw),
                    start=start,
                    end=start + timedelta(minutes=SESSION_MINUTES),
                    canceled=bool(raw.get("canceled")),
                )
            )
        return sessions

    async def get_sessions(
        self, coach_id: str, start: datetime, end: datetime
    ) -> list[TimeWindow]:
        return [
            TimeWindow(start=s.start, end=s.end)
            for s in await self.list_coach_sessions(coach_id)
            if not s.canceled
        ]

    async def list_coach_ids(self, page_size: int = 500, max_pages: int = 100) -> list[str]:
        ids: set[str] = set()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            page = 1
            while page <= max_pages:
                try:
                    resp = await client.get(
                        f"{self._base_url}/session/GetAllSessions",
                        params={"page": page, "pageSize": page_size},
                        headers=self._headers,
                    )
                    resp.raise_for_status()
                except Exception:
                    break  # ante un fallo de página, devolvemos lo recolectado
                data = resp.json().get("data", {})
                rows = data.get("result", {}).get("data", [])
                if not rows:
                    break
                for raw in rows:
                    cid = _coach_id_of(raw)
                    if cid:
                        ids.add(cid)
                total = data.get("total", 0)  # conteo total está a nivel de `data`
                if not isinstance(total, int) or page * page_size >= total:
                    break
                page += 1
        return sorted(ids)


class StubSessionsClient(SessionsClientBase):
    async def get_sessions(
        self, coach_id: str, start: datetime, end: datetime
    ) -> list[TimeWindow]:
        return []

    async def list_coach_sessions(self, coach_id: str) -> list[CoachSession]:
        return []

    async def list_coach_ids(self) -> list[str]:
        return []


def build_sessions_client(cfg: Settings) -> SessionsClientBase:
    if cfg.use_stub_clients:
        return StubSessionsClient()
    return SessionsClient(cfg.sessions_service_url, cfg.http_timeout_seconds, cfg.app_id)
