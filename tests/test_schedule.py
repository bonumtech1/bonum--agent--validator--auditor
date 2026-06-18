"""Tests de la conversión WorkSchedule (hora local) → ventana UTC."""

from datetime import datetime, timezone

from app.core.schedule import work_window_for

UTC = timezone.utc

# Coach en Europe/Madrid (UTC+2 en verano), trabaja L–V 08:00–17:00 local.
WS = {
    "Monday": {"work": True, "init": "08:00", "end": "17:00"},
    "Saturday": {"work": False, "init": "08:00", "end": "17:00"},
}


def test_madrid_monday_window_is_utc_plus_2():
    # Sesión el lunes 2026-06-22 a las 09:00Z.
    window = work_window_for(datetime(2026, 6, 22, 9, 0, tzinfo=UTC), WS, "Europe/Madrid")
    assert len(window) == 1
    # 08:00 local = 06:00Z ; 17:00 local = 15:00Z (verano, UTC+2)
    assert window[0].start == datetime(2026, 6, 22, 6, 0, tzinfo=UTC)
    assert window[0].end == datetime(2026, 6, 22, 15, 0, tzinfo=UTC)


def test_non_working_day_returns_empty():
    window = work_window_for(datetime(2026, 6, 20, 9, 0, tzinfo=UTC), WS, "Europe/Madrid")
    # Saturday: Work=False
    assert window == []


def test_day_without_schedule_returns_empty():
    window = work_window_for(datetime(2026, 6, 24, 9, 0, tzinfo=UTC), WS, "Europe/Madrid")
    # Wednesday no está en el mapa
    assert window == []


def test_utc_timezone_is_identity():
    ws = {"Monday": {"work": True, "init": "08:00", "end": "17:00"}}
    window = work_window_for(datetime(2026, 6, 22, 9, 0, tzinfo=UTC), ws, "UTC")
    assert window[0].start == datetime(2026, 6, 22, 8, 0, tzinfo=UTC)
    assert window[0].end == datetime(2026, 6, 22, 17, 0, tzinfo=UTC)
