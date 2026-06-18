"""Tests del detector de alertas (determinístico, sin BD)."""

from datetime import datetime, timezone

from app.alerts import detector
from app.config import Settings
from app.core.models import AuditResult, Finding, RiskLevel, Severity, SessionRequest

UTC = timezone.utc
CFG = Settings(use_stub_clients=True)


def _session() -> SessionRequest:
    return SessionRequest(
        coachId="coach-1",
        clientId="client-1",
        startTime=datetime(2026, 6, 20, 20, 0, tzinfo=UTC),
        endTime=datetime(2026, 6, 20, 21, 0, tzinfo=UTC),
        sessionId="sess-1",
    )


def test_clean_audit_no_alerts():
    res = AuditResult(session_id="sess-1", score=100, risk=RiskLevel.LOW, findings=[])
    assert detector.detect(res, _session(), CFG) == []


def test_low_score_triggers_alert():
    res = AuditResult(session_id="sess-1", score=40, risk=RiskLevel.HIGH, findings=[])
    alerts = detector.detect(res, _session(), CFG)
    assert any(a.type == "LOW_SCORE" for a in alerts)


def test_overloaded_coach_triggers_alert():
    res = AuditResult(
        session_id="sess-1",
        score=85,
        risk=RiskLevel.HIGH,
        findings=[Finding(code="COACH_OVERLOADED", severity=Severity.HIGH, message="x")],
    )
    alerts = detector.detect(res, _session(), CFG)
    overload = [a for a in alerts if a.type == "COACH_OVERLOADED"]
    assert len(overload) == 1
    # dedup_key incluye coach y día → estable para anti-duplicados
    assert overload[0].dedup_key == "COACH_OVERLOADED:coach-1:2026-06-20"


def test_outside_availability_triggers_out_of_hours_alert():
    res = AuditResult(
        session_id="sess-1",
        score=60,
        risk=RiskLevel.HIGH,
        findings=[Finding(code="OUTSIDE_AVAILABILITY", severity=Severity.HIGH, message="x")],
    )
    alerts = detector.detect(res, _session(), CFG)
    out = [a for a in alerts if a.type == "OUT_OF_HOURS"]
    assert len(out) == 1
    assert out[0].dedup_key == "OUT_OF_HOURS:sess-1"


def test_conflict_triggers_alert():
    res = AuditResult(
        session_id="sess-1",
        score=70,
        risk=RiskLevel.HIGH,
        findings=[Finding(code="SESSION_CONFLICT", severity=Severity.HIGH, message="x")],
    )
    alerts = detector.detect(res, _session(), CFG)
    assert any(a.type == "SESSION_CONFLICT" for a in alerts)
