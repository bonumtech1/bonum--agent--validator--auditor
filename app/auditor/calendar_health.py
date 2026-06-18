"""Auditor de salud de calendario (por coach).

Detecta configuraciones que rompen el agendamiento, usando solo lo accesible sin
credenciales de Nylas: perfil/timezone (Nexus), horario (WorkSchedule unprotected)
y disponibilidad (endpoint unprotected).

Hallazgos:
  • PROFILE_NOT_FOUND     (alto)  — el coach no existe en Nexus (huérfano)
  • MISSING_TIMEZONE      (alto)  — sin timezone → la disponibilidad se calcula mal
  • NO_WORK_SCHEDULE      (alto)  — no trabaja ningún día → no se le puede agendar
  • MISCONFIGURED_SCHEDULE(medio) — día laborable con horas inválidas (init>=end, etc.)
  • NO_CALENDAR_CONNECTED (alto)  — no tiene calendario conectado (sin providers)
  • BROKEN_CALENDAR_CONNECTION (alto) — el grant de Nylas está caído/expirado
                                    (requiere NYLAS_API_KEY; si no, se omite)
  • NOT_BOOKABLE          (alto)  — tiene días laborables pero 0 disponibilidad varios
                                    días seguidos (señal de calendario/timezone roto)
"""

import re
from datetime import datetime, timedelta

from app.clients.calendar import CalendarClientBase
from app.clients.users import UserClientBase
from app.core.models import CalendarHealthResult, Finding, Severity

_HM = re.compile(r"^\d{2}:\d{2}$")


def _valid_hm(value: str | None) -> bool:
    if not value or not _HM.match(value):
        return False
    h, m = value.split(":")
    return 0 <= int(h) <= 23 and 0 <= int(m) <= 59


def _schedule_findings(work_schedule: dict) -> list[Finding]:
    findings: list[Finding] = []
    working = {d: v for d, v in work_schedule.items() if v.get("work")}
    if not working:
        findings.append(
            Finding(
                code="NO_WORK_SCHEDULE",
                severity=Severity.HIGH,
                message="El coach no tiene ningún día laborable configurado.",
            )
        )
        return findings

    bad_days = []
    for day, v in working.items():
        init, end = v.get("init"), v.get("end")
        if not _valid_hm(init) or not _valid_hm(end) or init >= end:
            bad_days.append(day)
    if bad_days:
        findings.append(
            Finding(
                code="MISCONFIGURED_SCHEDULE",
                severity=Severity.MEDIUM,
                message=f"Horario inválido en: {', '.join(bad_days)} (revisar inicio/fin).",
            )
        )
    return findings


async def check_coach(
    coach_id: str,
    calendar: CalendarClientBase,
    users: UserClientBase,
    now: datetime,
    days_ahead: int = 7,
    nylas=None,
) -> CalendarHealthResult:
    meta = await users.get_coach_meta(coach_id)
    findings: list[Finding] = []

    if not meta["found"]:
        findings.append(
            Finding(
                code="PROFILE_NOT_FOUND",
                severity=Severity.HIGH,
                message="El coach no tiene perfil en Nexus (sesiones huérfanas).",
            )
        )
        return CalendarHealthResult(coach_id=coach_id, healthy=False, findings=findings)

    if not meta["timezone"]:
        findings.append(
            Finding(
                code="MISSING_TIMEZONE",
                severity=Severity.HIGH,
                message="El coach no tiene timezone → su disponibilidad se calcula mal.",
            )
        )

    # Conexión de calendario (Nylas).
    providers = meta.get("providers") or []
    if not providers:
        findings.append(
            Finding(
                code="NO_CALENDAR_CONNECTED",
                severity=Severity.HIGH,
                message="El coach no tiene calendario conectado (sin providers).",
            )
        )
    elif nylas is not None:
        for p in providers:
            status = await nylas.get_grant_status(p.get("grant"))
            if status != "valid":
                findings.append(
                    Finding(
                        code="BROKEN_CALENDAR_CONNECTION",
                        severity=Severity.HIGH,
                        message=f"Conexión {p.get('provider')} ({p.get('email')}) "
                        f"con estado '{status}' → aparece libre aunque su calendario "
                        "real no se puede leer.",
                    )
                )

    work_schedule = await calendar.get_work_schedule(coach_id)
    sched_findings = _schedule_findings(work_schedule)
    findings.extend(sched_findings)

    # "No bookable": solo tiene sentido si hay días laborables válidos.
    has_working_days = any(v.get("work") for v in work_schedule.values())
    blocked = any(f.code in ("NO_WORK_SCHEDULE",) for f in sched_findings)
    if has_working_days and not blocked:
        total_slots = 0
        for i in range(days_ahead):
            day = now + timedelta(days=i)
            slots = await calendar.get_availability(coach_id, day, day)
            total_slots += len(slots)
        if total_slots == 0:
            findings.append(
                Finding(
                    code="NOT_BOOKABLE",
                    severity=Severity.HIGH,
                    message=f"Días laborables configurados pero 0 disponibilidad en "
                    f"{days_ahead} días (posible calendario/timezone roto).",
                )
            )

    return CalendarHealthResult(
        coach_id=coach_id, healthy=len(findings) == 0, findings=findings
    )
