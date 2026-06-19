"""Modelos de datos compartidos por el validador y el auditor.

Todo lo relacionado con tiempo se maneja en datetimes *con zona horaria*
(timezone-aware). El motor de reglas asume esto y lo valida explícitamente.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Severity(str, Enum):
    INFO = "info"
    MEDIUM = "medium"
    HIGH = "high"


# ── Entrada ──────────────────────────────────────────────────────


class SessionRequest(BaseModel):
    """Sesión propuesta que el servicio de sesiones quiere validar/auditar."""

    coach_id: str = Field(..., alias="coachId")
    client_id: str = Field(..., alias="clientId")
    start_time: datetime = Field(..., alias="startTime")
    end_time: datetime = Field(..., alias="endTime")
    # Identificador opcional: presente al auditar una sesión ya creada.
    session_id: str | None = Field(default=None, alias="sessionId")

    model_config = {"populate_by_name": True}

    @field_validator("start_time", "end_time")
    @classmethod
    def must_be_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("las fechas deben incluir zona horaria (timezone-aware)")
        return v


# ── Datos que traemos de los servicios Node ──────────────────────


class TimeWindow(BaseModel):
    """Una ventana de tiempo: disponibilidad, bloqueo, u otra sesión."""

    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def must_be_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("las fechas deben incluir zona horaria (timezone-aware)")
        return v


class CoachContext(BaseModel):
    """Todo lo que el motor de reglas necesita saber del coach para un día dado.

    Lo arma el cliente de calendario (Nylas) + el de sesiones.
    """

    coach_id: str
    # Ventanas en las que el coach SÍ trabaja (horario laboral / disponibilidad Nylas).
    availability: list[TimeWindow] = Field(default_factory=list)
    # Ventanas bloqueadas: vacaciones, reuniones internas, eventos ocupados.
    blocks: list[TimeWindow] = Field(default_factory=list)
    # Otras sesiones ya agendadas del coach (para detectar solapes y carga).
    existing_sessions: list[TimeWindow] = Field(default_factory=list)


# ── Salida ───────────────────────────────────────────────────────


class Finding(BaseModel):
    """Un hallazgo individual de validación o auditoría."""

    code: str  # identificador estable, p.ej. "OUTSIDE_AVAILABILITY"
    severity: Severity
    message: str
    points: int = 0  # cuánto resta del score (0 = informativo)


class ValidationResult(BaseModel):
    """Respuesta del validador (síncrono)."""

    approved: bool
    risk: RiskLevel
    reasons: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)


class AuditResult(BaseModel):
    """Resultado de auditar una sesión (asíncrono). Lo persistimos en BD."""

    session_id: str | None = None
    score: int
    risk: RiskLevel
    findings: list[Finding] = Field(default_factory=list)


class CalendarHealthResult(BaseModel):
    """Resultado del chequeo de salud de calendario de un coach."""

    coach_id: str
    healthy: bool
    findings: list[Finding] = Field(default_factory=list)


class AlertStatus(str, Enum):
    NUEVA = "nueva"
    REVISADA = "revisada"
    IGNORADA = "ignorada"
    ESCALADA = "escalada"


class Alert(BaseModel):
    """Alerta operativa derivada de una auditoría. Se persiste en `audit_alerts`.

    `dedup_key` es el identificador estable (se usa como _id en Mongo) para evitar
    duplicados de la misma alerta.
    """

    dedup_key: str
    type: str  # LOW_SCORE | COACH_OVERLOADED | SESSION_CONFLICT
    severity: Severity
    title: str
    description: str
    coach_id: str | None = None
    coach_email: str | None = None
    session_id: str | None = None
    status: AlertStatus = AlertStatus.NUEVA
