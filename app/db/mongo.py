"""Conexión a MongoDB (async, vía pymongo.AsyncMongoClient).

El cliente se crea una sola vez al arrancar la app y se cierra al apagarla
(ver el lifespan en app/main.py). Si no hay URI configurada, devuelve None y
la persistencia queda desactivada — el servicio sigue funcionando.
"""

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings


async def connect(cfg: Settings) -> AsyncMongoClient | None:
    """Crea el cliente y verifica la conexión con un ping. None si no hay URI."""
    if not cfg.mongodb_uri:
        return None
    # Timeout corto: si Atlas no responde (red/allowlist), falla en ~3s y el
    # arranque continúa sin persistencia en vez de colgarse.
    client: AsyncMongoClient = AsyncMongoClient(
        cfg.mongodb_uri, serverSelectionTimeoutMS=3000, connectTimeoutMS=3000
    )
    await client.admin.command("ping")
    return client


def get_database(client: AsyncMongoClient, cfg: Settings) -> AsyncDatabase:
    return client[cfg.mongodb_db]


async def close(client: AsyncMongoClient | None) -> None:
    if client is not None:
        await client.aclose()
