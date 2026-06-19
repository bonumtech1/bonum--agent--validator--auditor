"""Detector de alertas — determinístico.

Toma el resultado de una auditoría y decide si dispara una o más alertas
operativas. Son comparaciones de umbrales; no hay IA.

Cada alerta lleva un `dedup_key` estable para no duplicarse:
  • LOW_SCORE / SESSION_CONFLICT → por sesión   (type:session_id)
  • COACH_OVERLOADED            → por coach y día (type:coach_id:YYYY-MM-DD)
"""

from app.config import Settings
from app.core.models import (
    Alert,
    AuditResult,
    CalendarHealthResult,
    Severity,
    SessionRequest,
)


def detect(
    result: AuditResult, s: SessionRequest, cfg: Settings, coach_email: str | None = None
) -> list[Alert]:
    alerts: list[Alert] = []
    sid = result.session_id or "sin-id"

    # 1) Score por debajo del umbral.
    if result.score < cfg.alert_low_score_threshold:
        alerts.append(
            Alert(
                dedup_key=f"LOW_SCORE:{sid}",
                type="LOW_SCORE",
                severity=Severity.HIGH,
                title="Sesión con score bajo",
                description=(
                    f"La sesión {sid} obtuvo score {result.score} "
                    f"(umbral {cfg.alert_low_score_threshold})."
                ),
                coach_id=s.coach_id,
                session_id=result.session_id,
            )
        )

    # 2) Coach sobrecargado (la auditoría ya lo detecta como hallazgo).
    if any(f.code == "COACH_OVERLOADED" for f in result.findings):
        day = s.start_time.date().isoformat()
        alerts.append(
            Alert(
                dedup_key=f"COACH_OVERLOADED:{s.coach_id}:{day}",
                type="COACH_OVERLOADED",
                severity=Severity.HIGH,
                title="Coach sobrecargado",
                description=f"El coach {s.coach_id} excede el máximo de sesiones el {day}.",
                coach_id=s.coach_id,
            )
        )

    # 3) Sesión fuera del horario laboral del coach (el caso central a vigilar).
    if any(f.code == "OUTSIDE_AVAILABILITY" for f in result.findings):
        alerts.append(
            Alert(
                dedup_key=f"OUT_OF_HOURS:{sid}",
                type="OUT_OF_HOURS",
                severity=Severity.HIGH,
                title="Sesión fuera de horario",
                description=(
                    f"La sesión {sid} del coach {s.coach_id} está fuera de su "
                    "horario laboral disponible."
                ),
                coach_id=s.coach_id,
                session_id=result.session_id,
            )
        )

    # 4) Conflicto con otra sesión.
    if any(f.code == "SESSION_CONFLICT" for f in result.findings):
        alerts.append(
            Alert(
                dedup_key=f"SESSION_CONFLICT:{sid}",
                type="SESSION_CONFLICT",
                severity=Severity.HIGH,
                title="Conflicto de sesiones",
                description=f"La sesión {sid} se solapa con otra del coach {s.coach_id}.",
                coach_id=s.coach_id,
                session_id=result.session_id,
            )
        )

    for a in alerts:
        a.coach_email = coach_email
    return alerts


def detect_calendar_health(
    result: CalendarHealthResult, coach_email: str | None = None
) -> list[Alert]:
    """Una alerta por cada hallazgo de salud de calendario (dedup por coach+código)."""
    alerts: list[Alert] = []
    for f in result.findings:
        alerts.append(
            Alert(
                dedup_key=f"{f.code}:{result.coach_id}",
                type=f.code,
                severity=f.severity,
                title="Problema de calendario",
                description=f"Coach {result.coach_id}: {f.message}",
                coach_id=result.coach_id,
                coach_email=coach_email,
            )
        )
    return alerts
