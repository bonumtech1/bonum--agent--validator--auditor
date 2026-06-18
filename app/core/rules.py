"""Motor de reglas determinístico.

Aquí vive TODA la lógica de decisión. No hay llamadas de red ni LLM: recibe
datos ya cargados (`CoachContext`) y devuelve hallazgos. Esto lo hace rápido,
barato, 100% reproducible y fácil de testear sin levantar nada.

Cada regla es una función pura que devuelve `Finding | None`.
El score arranca en 100 y cada hallazgo resta `points`.
"""

from datetime import datetime, timedelta

from app.config import Settings
from app.core.models import (
    AuditResult,
    CoachContext,
    Finding,
    RiskLevel,
    Severity,
    SessionRequest,
    TimeWindow,
    ValidationResult,
)


# ── Helpers de tiempo ────────────────────────────────────────────


def _overlaps(a_start: datetime, a_end: datetime, b: TimeWindow) -> bool:
    """True si [a_start, a_end) se solapa con la ventana b."""
    return a_start < b.end and b.start < a_end


def _contained_in_any(start: datetime, end: datetime, windows: list[TimeWindow]) -> bool:
    """True si [start, end] cabe completo dentro de alguna ventana."""
    return any(w.start <= start and end <= w.end for w in windows)


def _minutes(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 60.0


# ── Reglas individuales (funciones puras) ────────────────────────


def check_time_order(s: SessionRequest) -> Finding | None:
    if s.end_time <= s.start_time:
        return Finding(
            code="INVALID_TIME_RANGE",
            severity=Severity.HIGH,
            message="La hora de fin debe ser posterior a la de inicio.",
            points=100,
        )
    return None


def check_duration(s: SessionRequest, cfg: Settings) -> Finding | None:
    dur = _minutes(s.start_time, s.end_time)
    if dur < cfg.min_session_minutes:
        return Finding(
            code="DURATION_TOO_SHORT",
            severity=Severity.MEDIUM,
            message=f"Duración {dur:.0f} min < mínimo {cfg.min_session_minutes} min.",
            points=15,
        )
    if dur > cfg.max_session_minutes:
        return Finding(
            code="DURATION_TOO_LONG",
            severity=Severity.MEDIUM,
            message=f"Duración {dur:.0f} min > máximo {cfg.max_session_minutes} min.",
            points=15,
        )
    return None


def check_within_availability(s: SessionRequest, ctx: CoachContext) -> Finding | None:
    if not _contained_in_any(s.start_time, s.end_time, ctx.availability):
        return Finding(
            code="OUTSIDE_AVAILABILITY",
            severity=Severity.HIGH,
            message="La sesión cae fuera del horario disponible del coach.",
            points=40,
        )
    return None


def check_blocks(s: SessionRequest, ctx: CoachContext) -> Finding | None:
    for b in ctx.blocks:
        if _overlaps(s.start_time, s.end_time, b):
            return Finding(
                code="OVERLAPS_BLOCK",
                severity=Severity.HIGH,
                message=f"Choca con un bloqueo del coach ({b.start:%H:%M}–{b.end:%H:%M}).",
                points=40,
            )
    return None


def check_session_overlap(s: SessionRequest, ctx: CoachContext) -> Finding | None:
    for other in ctx.existing_sessions:
        # Ignora la propia sesión al auditar (mismo rango exacto).
        if other.start == s.start_time and other.end == s.end_time:
            continue
        if _overlaps(s.start_time, s.end_time, other):
            return Finding(
                code="SESSION_CONFLICT",
                severity=Severity.HIGH,
                message=f"Se solapa con otra sesión ({other.start:%H:%M}–{other.end:%H:%M}).",
                points=30,
            )
    return None


def check_lead_time(s: SessionRequest, cfg: Settings, now: datetime) -> Finding | None:
    lead = _minutes(now, s.start_time)
    if lead < cfg.min_lead_time_minutes:
        return Finding(
            code="INSUFFICIENT_LEAD_TIME",
            severity=Severity.MEDIUM,
            message=f"Se agenda con {lead:.0f} min de anticipación "
            f"(mínimo {cfg.min_lead_time_minutes} min).",
            points=10,
        )
    return None


def check_daily_load(s: SessionRequest, ctx: CoachContext, cfg: Settings) -> Finding | None:
    same_day = [
        w for w in ctx.existing_sessions if w.start.date() == s.start_time.date()
    ]
    count = len(same_day) + 1  # incluye la sesión evaluada
    if count > cfg.max_sessions_per_day:
        return Finding(
            code="COACH_OVERLOADED",
            severity=Severity.HIGH,
            message=f"El coach tendría {count} sesiones ese día "
            f"(máximo {cfg.max_sessions_per_day}).",
            points=15,
        )
    return None


def check_buffer(s: SessionRequest, ctx: CoachContext, cfg: Settings) -> Finding | None:
    """Verifica que haya un descanso mínimo entre sesiones contiguas."""
    buffer = timedelta(minutes=cfg.buffer_minutes)
    for other in ctx.existing_sessions:
        if other.start == s.start_time and other.end == s.end_time:
            continue
        if _overlaps(s.start_time, s.end_time, other):
            continue  # el solape lo reporta otra regla
        gap_after = other.start - s.end_time
        gap_before = s.start_time - other.end
        gap = max(gap_after, gap_before, timedelta(0))
        if timedelta(0) < gap < buffer:
            return Finding(
                code="INSUFFICIENT_BUFFER",
                severity=Severity.MEDIUM,
                message=f"Menos de {cfg.buffer_minutes} min de descanso "
                "entre sesiones contiguas.",
                points=10,
            )
    return None


# ── Orquestadores ────────────────────────────────────────────────

# Severidad → riesgo global del resultado.
def _risk_from_findings(findings: list[Finding]) -> RiskLevel:
    if any(f.severity == Severity.HIGH for f in findings):
        return RiskLevel.HIGH
    if any(f.severity == Severity.MEDIUM for f in findings):
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def validate(
    s: SessionRequest, ctx: CoachContext, cfg: Settings, now: datetime
) -> ValidationResult:
    """Validación síncrona en tiempo de creación.

    Bloquea (approved=False) ante cualquier hallazgo de severidad HIGH.
    """
    findings = [
        f
        for f in (
            check_time_order(s),
            check_duration(s, cfg),
            check_within_availability(s, ctx),
            check_blocks(s, ctx),
            check_session_overlap(s, ctx),
            check_lead_time(s, cfg, now),
            check_daily_load(s, ctx, cfg),
            check_buffer(s, ctx, cfg),
        )
        if f is not None
    ]

    has_blocker = any(f.severity == Severity.HIGH for f in findings)
    return ValidationResult(
        approved=not has_blocker,
        risk=_risk_from_findings(findings),
        reasons=[f.message for f in findings if f.severity == Severity.HIGH],
        findings=findings,
    )


def audit(s: SessionRequest, ctx: CoachContext, cfg: Settings, now: datetime) -> AuditResult:
    """Auditoría post-creación. Mismas reglas, pero produce un *score* (0–100).

    No bloquea nada; clasifica la calidad de la sesión ya existente.
    """
    findings = [
        f
        for f in (
            check_time_order(s),
            check_duration(s, cfg),
            check_within_availability(s, ctx),
            check_blocks(s, ctx),
            check_session_overlap(s, ctx),
            check_daily_load(s, ctx, cfg),
            check_buffer(s, ctx, cfg),
        )
        if f is not None
    ]

    score = max(0, 100 - sum(f.points for f in findings))
    return AuditResult(
        session_id=s.session_id,
        score=score,
        risk=_risk_from_findings(findings),
        findings=findings,
    )
