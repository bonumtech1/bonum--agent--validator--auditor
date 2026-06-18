"""Cliente al Nexus API (coaching) — de aquí sacamos el timezone del coach.

Endpoint: GET {NEXUS}/profiles/coach/{id} → data.userId.timezone (ej. "Europe/Madrid").
"""

from abc import ABC, abstractmethod

import httpx

from app.config import Settings


class UserClientBase(ABC):
    @abstractmethod
    async def get_timezone(self, coach_id: str) -> str:
        """Zona horaria IANA del coach (ej. 'Europe/Madrid'). 'UTC' si no se encuentra."""

    @abstractmethod
    async def get_coach_meta(self, coach_id: str) -> dict:
        """Metadatos de salud: {found, timezone, providers:[{provider,email,grant}]}."""


class UserClient(UserClientBase):
    def __init__(self, base_url: str, timeout: float, app_id: str):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._headers = {"x-app-id": app_id}

    async def get_timezone(self, coach_id: str) -> str:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base_url}/profiles/coach/{coach_id}", headers=self._headers
            )
        # Coach sin perfil en Nexus (huérfano): no es un error fatal del job.
        if resp.status_code == 404:
            return "UTC"
        resp.raise_for_status()
        payload = resp.json()
        try:
            return payload["data"]["userId"]["timezone"] or "UTC"
        except (KeyError, TypeError):
            return "UTC"

    async def get_coach_meta(self, coach_id: str) -> dict:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base_url}/profiles/coach/{coach_id}", headers=self._headers
            )
        if resp.status_code == 404:
            return {"found": False, "timezone": None, "providers": []}
        resp.raise_for_status()
        payload = resp.json()
        user = (payload.get("data") or {}).get("userId") or {}
        tz = user.get("timezone")
        providers = [
            {
                "provider": p.get("provider"),
                "email": p.get("email"),
                "grant": p.get("accessToken"),
            }
            for p in (user.get("providers") or [])
        ]
        return {"found": True, "timezone": tz or None, "providers": providers}


class StubUserClient(UserClientBase):
    async def get_timezone(self, coach_id: str) -> str:
        return "UTC"

    async def get_coach_meta(self, coach_id: str) -> dict:
        return {"found": True, "timezone": "UTC", "providers": []}


def build_user_client(cfg: Settings) -> UserClientBase:
    if cfg.use_stub_clients:
        return StubUserClient()
    return UserClient(cfg.nexus_api_url, cfg.http_timeout_seconds, cfg.app_id)
