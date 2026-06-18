"""Tests del auditor de salud de calendario (lógica pura, clientes fake)."""

from datetime import datetime, timezone

import pytest

from app.auditor import calendar_health
from app.core.models import TimeWindow

UTC = timezone.utc
NOW = datetime(2026, 6, 18, 9, 0, tzinfo=UTC)

FULL_WEEK = {
    d: {"work": True, "init": "08:00", "end": "17:00"}
    for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
}

# Un provider conectado por defecto (para que no salte NO_CALENDAR_CONNECTED).
ONE_PROVIDER = [{"provider": "google", "email": "c@x.com", "grant": "g1"}]


class FakeUsers:
    def __init__(self, meta):
        self._meta = meta

    async def get_timezone(self, coach_id):
        return self._meta.get("timezone") or "UTC"

    async def get_coach_meta(self, coach_id):
        return self._meta


class FakeCalendar:
    def __init__(self, work_schedule, slots_per_day=2):
        self._ws = work_schedule
        self._slots = slots_per_day

    async def get_availability(self, coach_id, start, end):
        return [TimeWindow(start=start, end=end)] * self._slots

    async def get_blocks(self, coach_id, start, end):
        return []

    async def get_work_schedule(self, coach_id):
        return self._ws


class FakeNylas:
    def __init__(self, status):
        self._status = status

    async def get_grant_status(self, grant_id):
        return self._status


def _meta(**kw):
    base = {"found": True, "timezone": "Europe/Madrid", "providers": ONE_PROVIDER}
    base.update(kw)
    return base


@pytest.mark.asyncio
async def test_healthy_coach_has_no_findings():
    res = await calendar_health.check_coach(
        "c1", FakeCalendar(FULL_WEEK), FakeUsers(_meta()), NOW, nylas=FakeNylas("valid")
    )
    assert res.healthy is True
    assert res.findings == []


@pytest.mark.asyncio
async def test_profile_not_found():
    res = await calendar_health.check_coach(
        "c1", FakeCalendar(FULL_WEEK), FakeUsers(_meta(found=False)), NOW
    )
    assert any(f.code == "PROFILE_NOT_FOUND" for f in res.findings)


@pytest.mark.asyncio
async def test_missing_timezone():
    res = await calendar_health.check_coach(
        "c1", FakeCalendar(FULL_WEEK), FakeUsers(_meta(timezone=None)), NOW
    )
    assert any(f.code == "MISSING_TIMEZONE" for f in res.findings)


@pytest.mark.asyncio
async def test_no_work_schedule():
    res = await calendar_health.check_coach(
        "c1", FakeCalendar({}), FakeUsers(_meta()), NOW
    )
    assert any(f.code == "NO_WORK_SCHEDULE" for f in res.findings)


@pytest.mark.asyncio
async def test_misconfigured_schedule_init_after_end():
    ws = {"Monday": {"work": True, "init": "18:00", "end": "09:00"}}
    res = await calendar_health.check_coach(
        "c1", FakeCalendar(ws), FakeUsers(_meta()), NOW
    )
    assert any(f.code == "MISCONFIGURED_SCHEDULE" for f in res.findings)


@pytest.mark.asyncio
async def test_no_calendar_connected():
    res = await calendar_health.check_coach(
        "c1", FakeCalendar(FULL_WEEK), FakeUsers(_meta(providers=[])), NOW
    )
    assert any(f.code == "NO_CALENDAR_CONNECTED" for f in res.findings)


@pytest.mark.asyncio
async def test_broken_calendar_connection():
    res = await calendar_health.check_coach(
        "c1",
        FakeCalendar(FULL_WEEK),
        FakeUsers(_meta()),
        NOW,
        nylas=FakeNylas("invalid"),
    )
    assert any(f.code == "BROKEN_CALENDAR_CONNECTION" for f in res.findings)


@pytest.mark.asyncio
async def test_not_bookable_when_no_availability():
    res = await calendar_health.check_coach(
        "c1",
        FakeCalendar(FULL_WEEK, slots_per_day=0),
        FakeUsers(_meta()),
        NOW,
        days_ahead=3,
    )
    assert any(f.code == "NOT_BOOKABLE" for f in res.findings)
