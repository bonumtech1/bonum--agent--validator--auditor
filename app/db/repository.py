"""Repositorio de auditorías sobre MongoDB.

Colecciones:
  • session_audits → una auditoría por sesión (lo que React muestra en la sesión)
  • audit_alerts   → alertas operativas (Fase 3; ya dejamos el método base)

Guarda documentos planos y serializables. Las fechas se guardan como datetime
nativos de Mongo (BSON date).
"""

from datetime import datetime, timezone

from pymongo.asynchronous.database import AsyncDatabase

from app.core.models import Alert, AuditResult, CalendarHealthResult, SessionRequest


def _audit_document(
    result: AuditResult,
    s: SessionRequest,
    now: datetime,
    coach_email: str | None = None,
    booked_at: datetime | None = None,
) -> dict:
    return {
        "session_id": result.session_id,
        "audit_type": "session",
        "coach_id": s.coach_id,
        "coach_email": coach_email,
        "booked_at": booked_at,
        "client_id": s.client_id,
        "start_time": s.start_time,
        "end_time": s.end_time,
        "score": result.score,
        "risk": result.risk.value,
        "findings": [f.model_dump() for f in result.findings],
        "created_at": now,
    }


class AuditRepository:
    def __init__(self, db: AsyncDatabase):
        self._db = db

    async def ensure_indexes(self) -> None:
        """Índices para consultar rápido por sesión, coach y fecha."""
        await self._db.session_audits.create_index("session_id")
        await self._db.session_audits.create_index("coach_id")
        await self._db.session_audits.create_index("created_at")
        await self._db.audit_alerts.create_index("status")
        await self._db.audit_alerts.create_index("severity")
        await self._db.audit_alerts.create_index("coach_id")
        await self._db.calendar_health.create_index("healthy")

    async def save_session_audit(
        self,
        result: AuditResult,
        s: SessionRequest,
        coach_email: str | None = None,
        booked_at: datetime | None = None,
    ) -> str:
        """Guarda (o reemplaza) la auditoría de una sesión. Devuelve el id."""
        now = datetime.now(timezone.utc)
        doc = _audit_document(result, s, now, coach_email, booked_at)
        if result.session_id:
            # Una auditoría vigente por sesión: upsert por session_id.
            await self._db.session_audits.replace_one(
                {"session_id": result.session_id}, doc, upsert=True
            )
            return result.session_id
        res = await self._db.session_audits.insert_one(doc)
        return str(res.inserted_id)

    async def get_session_audit(self, session_id: str) -> dict | None:
        """Devuelve la última auditoría de una sesión (sin el _id de Mongo)."""
        return await self._db.session_audits.find_one(
            {"session_id": session_id}, {"_id": 0}
        )

    async def list_session_audits(
        self,
        coach_id: str | None = None,
        risk: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Lista las auditorías de sesión (recientes primero), para el dashboard."""
        query: dict = {}
        if coach_id:
            query["coach_id"] = coach_id
        if risk:
            query["risk"] = risk
        cursor = (
            self._db.session_audits.find(query, {"_id": 0})
            .sort("created_at", -1)
            .limit(limit)
        )
        return [doc async for doc in cursor]

    # ── Alertas ──────────────────────────────────────────────────

    async def save_alert(self, alert: Alert) -> None:
        """Crea o actualiza una alerta. El `dedup_key` es el _id (anti-duplicados).

        Si la alerta ya existe se actualiza su descripción pero se PRESERVA el
        estado y la fecha de creación (no se pisa lo que el supervisor ya marcó).
        """
        now = datetime.now(timezone.utc)
        await self._db.audit_alerts.update_one(
            {"_id": alert.dedup_key},
            {
                "$set": {
                    "type": alert.type,
                    "severity": alert.severity.value,
                    "title": alert.title,
                    "description": alert.description,
                    "coach_id": alert.coach_id,
                    "coach_email": alert.coach_email,
                    "session_id": alert.session_id,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "status": alert.status.value,
                    "created_at": now,
                },
            },
            upsert=True,
        )

    async def list_alerts(
        self,
        status: str | None = None,
        severity: str | None = None,
        coach_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        query: dict = {}
        if status:
            query["status"] = status
        if severity:
            query["severity"] = severity
        if coach_id:
            query["coach_id"] = coach_id
        cursor = self._db.audit_alerts.find(query).sort("created_at", -1).limit(limit)
        results = []
        async for doc in cursor:
            doc["id"] = doc.pop("_id")  # exponer el dedup_key como "id"
            results.append(doc)
        return results

    # ── Salud de calendario ──────────────────────────────────────

    async def save_calendar_health(
        self, result: CalendarHealthResult, coach_email: str | None = None
    ) -> None:
        now = datetime.now(timezone.utc)
        await self._db.calendar_health.replace_one(
            {"_id": result.coach_id},
            {
                "_id": result.coach_id,
                "coach_id": result.coach_id,
                "coach_email": coach_email,
                "healthy": result.healthy,
                "findings": [f.model_dump() for f in result.findings],
                "checked_at": now,
            },
            upsert=True,
        )

    async def list_calendar_issues(self, limit: int = 200) -> list[dict]:
        cursor = self._db.calendar_health.find({"healthy": False}).limit(limit)
        results = []
        async for doc in cursor:
            doc["id"] = doc.pop("_id")
            results.append(doc)
        return results

    async def update_alert_status(self, alert_id: str, status: str) -> bool:
        """Cambia el estado de una alerta. Devuelve True si existía."""
        res = await self._db.audit_alerts.update_one(
            {"_id": alert_id},
            {"$set": {"status": status, "updated_at": datetime.now(timezone.utc)}},
        )
        return res.matched_count > 0
