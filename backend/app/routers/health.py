from fastapi import APIRouter
from redis import Redis
from sqlalchemy import text

from app.config import settings
from app.db import engine

router = APIRouter()


@router.get("/health")
def health() -> dict:
    postgres_ok = False
    redis_ok = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        postgres_ok = True
    except Exception:
        postgres_ok = False
    try:
        client = Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        try:
            redis_ok = bool(client.ping())
        finally:
            client.close()
    except Exception:
        redis_ok = False
    return {"ok": postgres_ok and redis_ok, "postgres": postgres_ok, "redis": redis_ok}
