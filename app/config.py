"""Configuración del servicio, cargada desde variables de entorno / .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # URLs de los microservicios Node (base, incluye el prefijo del servicio)
    calendar_service_url: str = "http://localhost:4001"
    sessions_service_url: str = "http://localhost:4002"
    # Nexus API (coaching): de aquí sale el timezone del coach.
    nexus_api_url: str = "http://localhost:4003"

    # Nylas: para verificar si la conexión de calendario del coach sigue viva.
    # Si la API key está vacía, ese chequeo se omite (graceful).
    nylas_api_key: str = ""
    nylas_api_uri: str = "https://api.us.nylas.com/"

    # Header obligatorio en ambos servicios: "coaching" | "mentoring".
    app_id: str = "coaching"

    # Si es true, los clientes devuelven datos simulados (sin red real).
    use_stub_clients: bool = True

    # Persistencia (MongoDB). La URI se lee de .env, NUNCA se hardcodea.
    # Si queda vacía, la persistencia se desactiva (el servicio sigue funcionando).
    mongodb_uri: str = ""
    mongodb_db: str = "coaching_audit"

    # Reglas de negocio (todas configurables vía entorno)
    min_session_minutes: int = 15
    max_session_minutes: int = 120
    max_sessions_per_day: int = 8
    buffer_minutes: int = 10
    min_lead_time_minutes: int = 60

    # Umbral de score por debajo del cual se genera una alerta.
    alert_low_score_threshold: int = 50

    # Job programado (auditoría automática de todos los coaches)
    scheduler_enabled: bool = True
    audit_interval_minutes: int = 60
    audit_future_only: bool = True  # el job solo audita sesiones futuras
    audit_max_concurrency: int = 5  # coaches auditados en paralelo

    # Salud de calendario (se incluye en el barrido programado)
    audit_calendar_health: bool = True
    calendar_health_days_ahead: int = 5

    http_timeout_seconds: float = 25.0


@lru_cache
def get_settings() -> Settings:
    """Devuelve la configuración (cacheada). Inyectable como dependencia FastAPI."""
    return Settings()
