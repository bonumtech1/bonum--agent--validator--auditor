"""Servicio de Agentes — Validador y Auditor de sesiones de coaching.

Endpoints actuales (Fase 0 + 1 + 2):
  GET  /health                  → estado del servicio (incluye estado de la BD)
  POST /validate-session        → validación síncrona (bloquea si es inválida)
  POST /audit-session           → auditoría post-creación (score + hallazgos), se persiste
  GET  /sessions/{id}/audit     → última auditoría guardada de una sesión

Pendiente (fases siguientes): alertas, auditor programado, dashboard, resumen LLM.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.alerts import detector
from app.alerts.view import render_alerts_page
from app.auditor import runner
from app.auditor.scheduler import run_full_audit, start_scheduler
from app.clients.calendar import build_calendar_client
from app.clients.sessions import build_sessions_client
from app.clients.users import build_user_client
from app.config import Settings, get_settings
from app.core import rules
from app.core.context import build_audit_context, build_coach_context
from app.core.models import AlertStatus, AuditResult, SessionRequest, ValidationResult
from app.db import mongo
from app.db.repository import AuditRepository


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    # Mongo es opcional: el validador no lo necesita. Si no conecta, el servicio
    # arranca igual con la persistencia desactivada (no tumbamos el arranque).
    client = None
    repo: AuditRepository | None = None
    try:
        client = await mongo.connect(cfg)
        if client is not None:
            repo = AuditRepository(mongo.get_database(client, cfg))
            await repo.ensure_indexes()
    except Exception as exc:
        logging.getLogger("main").error("Mongo no disponible, persistencia OFF: %s", exc)
        client = None
        repo = None
    app.state.mongo_client = client
    app.state.audit_repo = repo
    app.state.last_audit_run = None
    app.state.audit_running = False
    app.state.audit_task = None

    scheduler = None
    if cfg.scheduler_enabled:
        scheduler = start_scheduler(app, cfg)

    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        await mongo.close(client)


app = FastAPI(
    title="Coaching Audit & Validation Agent", version="0.2.0", lifespan=lifespan
)

# CORS: el dashboard (navegador) consume estos endpoints desde otro origen.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev; en prod restringir al dominio del dashboard
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_repo(request: Request) -> AuditRepository | None:
    return request.app.state.audit_repo


@app.get("/health")
def health(request: Request) -> dict:
    return {"status": "ok", "db": "connected" if request.app.state.audit_repo else "disabled"}


@app.post("/validate-session", response_model=ValidationResult)
async def validate_session(
    s: SessionRequest, cfg: Settings = Depends(get_settings)
) -> ValidationResult:
    """Lo llama el servicio de sesiones ANTES de persistir la sesión."""
    calendar = build_calendar_client(cfg)
    sessions = build_sessions_client(cfg)
    ctx = await build_coach_context(s, calendar, sessions)
    return rules.validate(s, ctx, cfg, now=datetime.now(timezone.utc))


@app.post("/audit-session", response_model=AuditResult)
async def audit_session(
    s: SessionRequest,
    cfg: Settings = Depends(get_settings),
    repo: AuditRepository | None = Depends(get_repo),
) -> AuditResult:
    """Audita una sesión YA creada, persiste el resultado y lo devuelve."""
    calendar = build_calendar_client(cfg)
    sessions = build_sessions_client(cfg)
    users = build_user_client(cfg)
    ctx = await build_audit_context(s, calendar, sessions, users)
    result = rules.audit(s, ctx, cfg, now=datetime.now(timezone.utc))
    if repo is not None:
        await repo.save_session_audit(result, s)
        # Dispara alertas operativas si la auditoría cruza algún umbral.
        for alert in detector.detect(result, s, cfg):
            await repo.save_alert(alert)
    return result


@app.post("/audit-coach/{coach_id}")
async def audit_coach(
    coach_id: str,
    future_only: bool = False,
    cfg: Settings = Depends(get_settings),
    repo: AuditRepository | None = Depends(get_repo),
) -> dict:
    """Audita TODAS las sesiones de un coach (lote). Persiste y devuelve resumen."""
    calendar = build_calendar_client(cfg)
    sessions = build_sessions_client(cfg)
    users = build_user_client(cfg)
    results = await runner.run_coach_audit(
        coach_id, calendar, sessions, users, cfg, repo,
        now=datetime.now(timezone.utc), future_only=future_only,
    )
    return runner.summarize(results)


async def _run_audit_bg(app, cfg: Settings) -> None:
    app.state.audit_running = True
    try:
        await run_full_audit(app, cfg)
    except Exception as exc:  # no dejar el flag colgado si algo falla
        logging.getLogger("main").error("Barrido falló: %s", exc)
    finally:
        app.state.audit_running = False


@app.post("/audit/run-all")
async def audit_run_all(request: Request, cfg: Settings = Depends(get_settings)) -> dict:
    """Lanza el barrido en SEGUNDO PLANO y responde de inmediato.

    El barrido completo (todos los coaches contra prod) tarda minutos; correrlo
    síncrono haría que el proxy/navegador corten por timeout. Por eso se dispara
    como tarea de fondo y el dashboard consulta /audit/last-run para el progreso.
    """
    app = request.app
    if getattr(app.state, "audit_running", False):
        return {"status": "already_running"}
    # Guardamos la referencia para que la tarea no la recoja el GC.
    app.state.audit_task = asyncio.create_task(_run_audit_bg(app, cfg))
    return {"status": "started"}


@app.get("/audit/last-run")
def audit_last_run(request: Request) -> dict:
    """Resumen del último barrido + si hay uno en curso (`running`)."""
    last = request.app.state.last_audit_run
    running = getattr(request.app.state, "audit_running", False)
    base = last or {"status": "sin barridos todavía"}
    return {**base, "running": running}


@app.post("/audit/calendar-health/{coach_id}")
async def audit_calendar_health_coach(
    coach_id: str,
    cfg: Settings = Depends(get_settings),
    repo: AuditRepository | None = Depends(get_repo),
) -> dict:
    """Chequea la salud de calendario de un coach (timezone, horario, agendable)."""
    calendar = build_calendar_client(cfg)
    users = build_user_client(cfg)
    result = await runner.run_coach_health(
        coach_id, calendar, users, cfg, repo, now=datetime.now(timezone.utc)
    )
    return result.model_dump()


@app.post("/audit/calendar-health")
async def audit_calendar_health_all(
    cfg: Settings = Depends(get_settings), repo: AuditRepository | None = Depends(get_repo)
) -> dict:
    """Chequea la salud de calendario de TODOS los coaches."""
    calendar = build_calendar_client(cfg)
    sessions = build_sessions_client(cfg)
    users = build_user_client(cfg)
    return await runner.run_all_health(
        calendar, sessions, users, cfg, repo, now=datetime.now(timezone.utc)
    )


@app.get("/calendar-health/issues")
async def calendar_health_issues(repo: AuditRepository | None = Depends(get_repo)) -> list[dict]:
    """Coaches con problemas de calendario detectados (para el dashboard)."""
    if repo is None:
        raise HTTPException(status_code=503, detail="Persistencia desactivada")
    return await repo.list_calendar_issues()


@app.get("/session-audits")
async def list_session_audits(
    coachId: str | None = None,
    risk: str | None = None,
    repo: AuditRepository | None = Depends(get_repo),
) -> list[dict]:
    """Lista las auditorías de sesión (score + hallazgos) para el dashboard."""
    if repo is None:
        raise HTTPException(status_code=503, detail="Persistencia desactivada")
    return await repo.list_session_audits(coach_id=coachId, risk=risk)


@app.get("/sessions/{session_id}/audit")
async def get_session_audit(
    session_id: str, repo: AuditRepository | None = Depends(get_repo)
) -> dict:
    """Última auditoría guardada de una sesión (para mostrar en React)."""
    if repo is None:
        raise HTTPException(status_code=503, detail="Persistencia desactivada")
    audit = await repo.get_session_audit(session_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Sesión sin auditoría")
    return audit


# ── Alertas ──────────────────────────────────────────────────────


@app.get("/alerts")
async def list_alerts(
    status: str | None = None,
    severity: str | None = None,
    coachId: str | None = None,
    repo: AuditRepository | None = Depends(get_repo),
) -> list[dict]:
    """Lista alertas con filtros opcionales: status, severity, coachId."""
    if repo is None:
        raise HTTPException(status_code=503, detail="Persistencia desactivada")
    return await repo.list_alerts(status=status, severity=severity, coach_id=coachId)


@app.patch("/alerts/{alert_id}")
async def update_alert(
    alert_id: str, status: AlertStatus, repo: AuditRepository | None = Depends(get_repo)
) -> dict:
    """Cambia el estado de una alerta: revisada | ignorada | escalada."""
    if repo is None:
        raise HTTPException(status_code=503, detail="Persistencia desactivada")
    found = await repo.update_alert_status(alert_id, status.value)
    if not found:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    return {"id": alert_id, "status": status.value}


@app.get("/alerts/ui", response_class=HTMLResponse)
async def alerts_ui(repo: AuditRepository | None = Depends(get_repo)) -> str:
    """Vista HTML provisional para ver las alertas en el navegador."""
    alerts = await repo.list_alerts() if repo is not None else []
    return render_alerts_page(alerts)
