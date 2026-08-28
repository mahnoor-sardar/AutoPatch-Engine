import asyncio
import json
import logging

from redis import Redis
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Device, PushEvent, SandboxRun
from app.services import fcm

logger = logging.getLogger(__name__)

RUN_CHANNEL = "autopatch:runs"


def publish_run_update(payload: dict | None = None) -> None:
    body = json.dumps(payload or {"type": "refresh"})
    client = None
    try:
        client = Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        client.publish(RUN_CHANNEL, body)
    except Exception:
        logger.exception("failed to publish run update")
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


async def subscribe_run_updates():
    from redis import asyncio as redis_async

    client = redis_async.from_url(settings.redis_url)
    pubsub = client.pubsub()
    await pubsub.subscribe(RUN_CHANNEL)
    try:
        async for message in pubsub.listen():
            if message.get("type") == "message":
                yield message
    finally:
        try:
            await pubsub.unsubscribe(RUN_CHANNEL)
        except Exception:
            pass
        await client.aclose()


def notify_run_event(
    db: Session,
    run: SandboxRun,
    title: str,
    body: str,
    extra: dict[str, str] | None = None,
) -> None:
    data = {
        "run_id": str(run.id),
        "status": run.status,
        "repository": run.repo,
    }
    if extra:
        data.update(extra)

    for device in db.query(Device).all():
        status = "sent"
        try:
            fcm.send_push_with_timeout(device.fcm_token, title, body, data)
        except Exception:
            status = "failed"
        db.add(
            PushEvent(
                device_id=device.device_id,
                title=title,
                status=status,
            )
        )
    db.commit()
    publish_run_update(
        {
            "type": "run_event",
            "title": title,
            "body": body,
            "run_id": run.id,
            "status": run.status,
            "current_diff": run.current_diff,
            "pr_url": run.pr_url,
        }
    )
