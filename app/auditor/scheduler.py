"""Job programado: audita a todos los coaches cada N minutos (default 60).

Usa APScheduler sobre el event loop de la app. El estado del último barrido se
guarda en `app.state.last_audit_run` para consultarlo vía /audit/last-run.
"""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.auditor import runner
from app.clients.calendar import build_calendar_client
from app.clients.sessions import build_sessions_client
from app.clients.users import build_user_client
from app.config import Settings

logger = logging.getLogger("auditor.scheduler")


async def run_full_audit(app: FastAPI, cfg: Settings) -> dict:
    """Ejecuta un barrido completo y guarda el resultado en app.state."""
    calendar = build_calendar_client(cfg)
    sessions = build_sessions_client(cfg)
    users = build_user_client(cfg)
    repo = app.state.audit_repo
    now = datetime.now(timezone.utc)
    logger.info("Auditoría programada: iniciando barrido de coaches")

    # Resiliente: si una parte falla, no perdemos la otra ni el resumen.
    summary: dict = {"ran_at": now.isoformat()}
    try:
        summary.update(await runner.run_all_coaches(calendar, sessions, users, cfg, repo, now=now))
    except Exception as exc:
        logger.error("run_all_coaches falló: %s", exc)
        summary["sessions_error"] = str(exc)

    if cfg.audit_calendar_health:
        try:
            health = await runner.run_all_health(calendar, sessions, users, cfg, repo, now=now)
            summary["calendar_health"] = {
                "unhealthy": health["unhealthy"],
                "coaches": health["coaches"],
            }
        except Exception as exc:
            logger.error("run_all_health falló: %s", exc)
            summary["calendar_health_error"] = str(exc)

    app.state.last_audit_run = summary
    logger.info("Auditoría programada terminada: %s", summary)
    return summary


def start_scheduler(app: FastAPI, cfg: Settings) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        run_full_audit,
        trigger="interval",
        minutes=cfg.audit_interval_minutes,
        args=[app, cfg],
        id="audit_all_coaches",
        max_instances=1,          # no solapar barridos
        coalesce=True,            # si se atrasa, ejecuta una sola vez
        next_run_time=None,       # no corre al arrancar; espera el primer intervalo
    )
    scheduler.start()
    logger.info("Scheduler iniciado: cada %s min", cfg.audit_interval_minutes)
    return scheduler
