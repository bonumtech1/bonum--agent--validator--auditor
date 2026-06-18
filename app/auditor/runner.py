"""Auditor en lote: audita TODAS las sesiones de un coach de una sola pasada.

Trae timezone + WorkSchedule + sesiones UNA vez y audita cada sesión en memoria
(eficiente, evita refetch por sesión). Persiste cada auditoría y genera alertas.
"""

import asyncio
from datetime import datetime

from app.alerts import detector
from app.auditor import calendar_health
from app.clients.calendar import CalendarClientBase
from app.clients.sessions import SessionsClientBase
from app.clients.users import UserClientBase
from app.config import Settings
from app.core import rules
from app.core.models import (
    AuditResult,
    CalendarHealthResult,
    CoachContext,
    SessionRequest,
    TimeWindow,
)
from app.core.schedule import work_window_for
from app.db.repository import AuditRepository


async def run_coach_audit(
    coach_id: str,
    calendar: CalendarClientBase,
    sessions: SessionsClientBase,
    users: UserClientBase,
    cfg: Settings,
    repo: AuditRepository | None,
    now: datetime,
    future_only: bool = False,
) -> list[AuditResult]:
    tz = await users.get_timezone(coach_id)
    work_schedule = await calendar.get_work_schedule(coach_id)
    # Sin horario configurado no podemos juzgar disponibilidad → se omite el coach
    # (evita marcar todas sus sesiones como "fuera de horario" por falta de datos).
    if not work_schedule:
        return []
    coach_sessions = [s for s in await sessions.list_coach_sessions(coach_id) if not s.canceled]
    if future_only:
        coach_sessions = [s for s in coach_sessions if s.start >= now]

    # Ventanas de todas las sesiones, para detectar solapes entre ellas.
    all_windows = [TimeWindow(start=s.start, end=s.end) for s in coach_sessions]

    results: list[AuditResult] = []
    for s in coach_sessions:
        req = SessionRequest(
            coachId=coach_id,
            clientId=s.coachee_id or "unknown",
            startTime=s.start,
            endTime=s.end,
            sessionId=s.session_id,
        )
        window = work_window_for(s.start, work_schedule, tz)
        others = [w for w in all_windows if not (w.start == s.start and w.end == s.end)]
        ctx = CoachContext(
            coach_id=coach_id, availability=window, blocks=[], existing_sessions=others
        )
        result = rules.audit(req, ctx, cfg, now)
        if repo is not None:
            await repo.save_session_audit(result, req)
            for alert in detector.detect(result, req, cfg):
                await repo.save_alert(alert)
        results.append(result)
    return results


async def run_all_coaches(
    calendar: CalendarClientBase,
    sessions: SessionsClientBase,
    users: UserClientBase,
    cfg: Settings,
    repo: AuditRepository | None,
    now: datetime,
) -> dict:
    """Audita TODOS los coaches con sesiones (lo que ejecuta el job horario).

    Lista los coaches y los audita en paralelo con concurrencia limitada.
    Devuelve un resumen agregado del barrido completo.
    """
    coach_ids = await sessions.list_coach_ids()
    semaphore = asyncio.Semaphore(cfg.audit_max_concurrency)

    async def audit_one(coach_id: str) -> dict:
        async with semaphore:
            try:
                results = await run_coach_audit(
                    coach_id, calendar, sessions, users, cfg, repo,
                    now=now, future_only=cfg.audit_future_only,
                )
                return {"coach_id": coach_id, "ok": True, **summarize(results)}
            except Exception as exc:  # un coach que falle no tumba el barrido
                return {"coach_id": coach_id, "ok": False, "error": str(exc)}

    per_coach = await asyncio.gather(*(audit_one(cid) for cid in coach_ids))

    audited_sessions = sum(c.get("audited", 0) for c in per_coach if c["ok"])
    high = sum(c.get("by_risk", {}).get("high", 0) for c in per_coach if c["ok"])
    failed = [c["coach_id"] for c in per_coach if not c["ok"]]
    return {
        "ran_at": now.isoformat(),
        "coaches": len(coach_ids),
        "coaches_failed": failed,
        "audited_sessions": audited_sessions,
        "high_risk_sessions": high,
    }


async def run_coach_health(
    coach_id: str,
    calendar: CalendarClientBase,
    users: UserClientBase,
    cfg: Settings,
    repo: AuditRepository | None,
    now: datetime,
) -> CalendarHealthResult:
    result = await calendar_health.check_coach(
        coach_id, calendar, users, now, days_ahead=cfg.calendar_health_days_ahead
    )
    if repo is not None:
        await repo.save_calendar_health(result)
        for alert in detector.detect_calendar_health(result):
            await repo.save_alert(alert)
    return result


async def run_all_health(
    calendar: CalendarClientBase,
    sessions: SessionsClientBase,
    users: UserClientBase,
    cfg: Settings,
    repo: AuditRepository | None,
    now: datetime,
) -> dict:
    coach_ids = await sessions.list_coach_ids()
    semaphore = asyncio.Semaphore(cfg.audit_max_concurrency)

    async def check_one(coach_id: str) -> dict:
        async with semaphore:
            try:
                r = await run_coach_health(coach_id, calendar, users, cfg, repo, now)
                return {
                    "coach_id": coach_id,
                    "ok": True,
                    "healthy": r.healthy,
                    "issues": [f.code for f in r.findings],
                }
            except Exception as exc:
                return {"coach_id": coach_id, "ok": False, "error": str(exc)}

    per_coach = await asyncio.gather(*(check_one(cid) for cid in coach_ids))
    unhealthy = [c for c in per_coach if c["ok"] and not c["healthy"]]
    return {
        "ran_at": now.isoformat(),
        "coaches": len(coach_ids),
        "unhealthy": len(unhealthy),
        "issues": unhealthy,
        "coaches_failed": [c["coach_id"] for c in per_coach if not c["ok"]],
    }


def summarize(results: list[AuditResult]) -> dict:
    """Resumen agregado para la respuesta del endpoint / dashboard."""
    total = len(results)
    by_risk = {"low": 0, "medium": 0, "high": 0}
    for r in results:
        by_risk[r.risk.value] += 1
    avg = round(sum(r.score for r in results) / total, 1) if total else 0
    return {
        "audited": total,
        "avg_score": avg,
        "by_risk": by_risk,
        "sessions": [
            {
                "session_id": r.session_id,
                "score": r.score,
                "risk": r.risk.value,
                "findings": [f.code for f in r.findings],
            }
            for r in results
        ],
    }
