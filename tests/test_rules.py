"""Tests del motor de reglas determinístico (sin red, sin LLM)."""

from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.core import rules
from app.core.models import CoachContext, RiskLevel, SessionRequest, TimeWindow

UTC = timezone.utc
CFG = Settings(use_stub_clients=True)

# "Ahora" fijo para que las pruebas de anticipación sean deterministas.
NOW = datetime(2026, 6, 20, 8, 0, tzinfo=UTC)


def _session(start_h: int, end_h: int, day: int = 20) -> SessionRequest:
    return SessionRequest(
        coachId="coach-1",
        clientId="client-1",
        startTime=datetime(2026, 6, day, start_h, 0, tzinfo=UTC),
        endTime=datetime(2026, 6, day, end_h, 0, tzinfo=UTC),
        sessionId="sess-1",
    )


def _workday() -> CoachContext:
    """Coach disponible 09:00–18:00, sin bloqueos ni otras sesiones."""
    return CoachContext(
        coach_id="coach-1",
        availability=[
            TimeWindow(
                start=datetime(2026, 6, 20, 9, 0, tzinfo=UTC),
                end=datetime(2026, 6, 20, 18, 0, tzinfo=UTC),
            )
        ],
    )


# ── Caso feliz ───────────────────────────────────────────────────


def test_valid_session_is_approved():
    res = rules.validate(_session(10, 11), _workday(), CFG, NOW)
    assert res.approved is True
    assert res.risk == RiskLevel.LOW
    assert res.findings == []


# ── Fuera de horario ─────────────────────────────────────────────


def test_outside_availability_is_rejected():
    res = rules.validate(_session(19, 20), _workday(), CFG, NOW)
    assert res.approved is False
    assert res.risk == RiskLevel.HIGH
    assert any(f.code == "OUTSIDE_AVAILABILITY" for f in res.findings)


# ── Bloqueo del coach ────────────────────────────────────────────


def test_overlapping_block_is_rejected():
    ctx = _workday()
    ctx.blocks = [
        TimeWindow(
            start=datetime(2026, 6, 20, 10, 0, tzinfo=UTC),
            end=datetime(2026, 6, 20, 12, 0, tzinfo=UTC),
        )
    ]
    res = rules.validate(_session(10, 11), ctx, CFG, NOW)
    assert res.approved is False
    assert any(f.code == "OVERLAPS_BLOCK" for f in res.findings)


# ── Solape con otra sesión ───────────────────────────────────────


def test_session_conflict_is_rejected():
    ctx = _workday()
    ctx.existing_sessions = [
        TimeWindow(
            start=datetime(2026, 6, 20, 10, 30, tzinfo=UTC),
            end=datetime(2026, 6, 20, 11, 30, tzinfo=UTC),
        )
    ]
    res = rules.validate(_session(10, 11), ctx, CFG, NOW)
    assert res.approved is False
    assert any(f.code == "SESSION_CONFLICT" for f in res.findings)


# ── Anticipación insuficiente ────────────────────────────────────


def test_insufficient_lead_time_is_warning_not_blocker():
    # Sesión 09:00 (dentro de horario), pero "ahora" son las 08:30 → 30 min < 60.
    now = datetime(2026, 6, 20, 8, 30, tzinfo=UTC)
    res = rules.validate(_session(9, 10), _workday(), CFG, now)
    # Es un warning MEDIUM: no bloquea, pero baja el riesgo.
    assert any(f.code == "INSUFFICIENT_LEAD_TIME" for f in res.findings)
    assert res.approved is True


# ── Duración inválida ────────────────────────────────────────────


def test_duration_too_long_is_warning():
    res = rules.validate(_session(9, 13), _workday(), CFG, NOW)  # 240 min
    assert any(f.code == "DURATION_TOO_LONG" for f in res.findings)


# ── Auditoría: score ─────────────────────────────────────────────


def test_audit_clean_session_scores_100():
    res = rules.audit(_session(10, 11), _workday(), CFG, NOW)
    assert res.score == 100
    assert res.risk == RiskLevel.LOW


def test_audit_subtracts_points_per_finding():
    res = rules.audit(_session(19, 20), _workday(), CFG, NOW)  # fuera de horario
    assert res.score == 60  # 100 - 40 por OUTSIDE_AVAILABILITY
    assert res.risk == RiskLevel.HIGH


def test_audit_overloaded_coach():
    ctx = _workday()
    # 8 sesiones ya agendadas ese día → la novena excede el máximo.
    ctx.existing_sessions = [
        TimeWindow(
            start=datetime(2026, 6, 20, 9 + i, 0, tzinfo=UTC),
            end=datetime(2026, 6, 20, 9 + i, 30, tzinfo=UTC),
        )
        for i in range(8)
    ]
    res = rules.audit(_session(17, 18), ctx, CFG, NOW)
    assert any(f.code == "COACH_OVERLOADED" for f in res.findings)
