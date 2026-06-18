"""Cliente a Nylas — para verificar si el grant (conexión) de un coach sigue vivo.

Si no hay API key configurada, `build_nylas_client` devuelve None y el chequeo
de conexiones se omite (la salud de calendario sigue funcionando sin él).
"""

import httpx

from app.config import Settings


class NylasClient:
    def __init__(self, api_key: str, api_uri: str, timeout: float):
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._base = api_uri.rstrip("/")
        self._timeout = timeout

    async def get_grant_status(self, grant_id: str) -> str:
        """Devuelve 'valid', 'invalid', 'not_found' o 'error' para un grant."""
        if not grant_id:
            return "not_found"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base}/v3/grants/{grant_id}", headers=self._headers
                )
            if resp.status_code == 404:
                return "not_found"
            resp.raise_for_status()
            data = resp.json().get("data", {})
            # Nylas v3: grant_status suele ser "valid" | "invalid".
            return data.get("grant_status") or "error"
        except Exception:
            return "error"


def build_nylas_client(cfg: Settings) -> NylasClient | None:
    if cfg.use_stub_clients or not cfg.nylas_api_key:
        return None
    return NylasClient(cfg.nylas_api_key, cfg.nylas_api_uri, cfg.http_timeout_seconds)
