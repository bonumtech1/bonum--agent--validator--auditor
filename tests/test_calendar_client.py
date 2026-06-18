"""Tests del CalendarClient real: parseo de la respuesta de /availability.

Usa httpx.MockTransport para simular el servicio de calendario, sin red.
Verifica que la respuesta real `{statusCode, message, data:[iso,...]}` se
traduce a ventanas de 1 hora y que el validador decide bien sobre ellas.
"""

from datetime import datetime, timezone

import httpx
import pytest

from app.clients.calendar import CalendarClient

UTC = timezone.utc


@pytest.mark.asyncio
async def test_parses_availability_into_hourly_windows(monkeypatch):
    slots = ["2026-06-20T13:00:00.000Z", "2026-06-20T14:00:00.000Z"]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-app-id"] == "coaching"
        assert request.url.params["userid"] == "coach-1"
        return httpx.Response(
            200, json={"statusCode": "10000", "message": "ok", "data": slots}
        )

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    client = CalendarClient("https://calendar.example/calendar/api", 5.0, "coaching")
    windows = await client.get_availability(
        "coach-1",
        datetime(2026, 6, 20, 13, 0, tzinfo=UTC),
        datetime(2026, 6, 20, 14, 0, tzinfo=UTC),
    )

    assert len(windows) == 2
    assert windows[0].start == datetime(2026, 6, 20, 13, 0, tzinfo=UTC)
    assert windows[0].end == datetime(2026, 6, 20, 14, 0, tzinfo=UTC)  # +1h
    assert windows[1].start == datetime(2026, 6, 20, 14, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_empty_availability_returns_no_windows(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"statusCode": "10000", "message": "ok", "data": []})

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: original(*a, **{**k, "transport": transport})
    )

    client = CalendarClient("https://calendar.example/calendar/api", 5.0, "coaching")
    windows = await client.get_availability(
        "coach-x",
        datetime(2026, 6, 20, 10, 0, tzinfo=UTC),
        datetime(2026, 6, 20, 11, 0, tzinfo=UTC),
    )
    assert windows == []
