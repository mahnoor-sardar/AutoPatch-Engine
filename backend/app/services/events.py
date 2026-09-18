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
MAX_AGENT_LOG_CHUNK = 4096
AGENT_LOG_OVERLAP = 128
_pending_agent_logs: dict[tuple[int, str], str] = {}


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

    for device in db.query(Device).filter(Device.revoked_at.is_(None)).all():
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


def _emit_agent_log_chunk(run_id: int, stream: str, text: str) -> None:
    if not text:
        return
    if len(text) > MAX_AGENT_LOG_CHUNK:
        text = text[:MAX_AGENT_LOG_CHUNK]
    publish_run_update(
        {
            "type": "agent_log",
            "run_id": run_id,
            "stream": stream,
            "chunk": text,
        }
    )


def _emit_sanitized_prefix(run_id: int, stream: str, raw: str, token: str) -> str:
    """Emit a sanitized prefix of raw, holding at most AGENT_LOG_OVERLAP bytes."""
    from app.services.e2b_runner import sanitize_log_text

    while len(raw) > AGENT_LOG_OVERLAP:
        extra, hold = raw[:-AGENT_LOG_OVERLAP], raw[-AGENT_LOG_OVERLAP:]
        combined = sanitize_log_text(extra + hold, token)
        hold_sanitized = sanitize_log_text(hold, token)
        if hold_sanitized and combined.endswith(hold_sanitized):
            _emit_agent_log_chunk(run_id, stream, combined[: -len(hold_sanitized)])
            raw = hold
        else:
            _emit_agent_log_chunk(run_id, stream, combined)
            raw = ""
            break
    return raw


def flush_agent_logs(run_id: int, token: str = "") -> None:
    """Publish any held remainder for a run so secrets can be matched, then drop state."""
    from app.services.e2b_runner import sanitize_log_text

    for stream in ("stdout", "stderr"):
        raw = _pending_agent_logs.pop((run_id, stream), "")
        if raw:
            _emit_agent_log_chunk(run_id, stream, sanitize_log_text(raw, token))


def publish_agent_log(
    run_id: int,
    stream: str,
    chunk: str,
    token: str = "",
) -> None:
    """Publish sandbox stdout/stderr to RUN_CHANNEL without FCM."""
    from app.services.e2b_runner import sanitize_log_text

    if stream not in ("stdout", "stderr"):
        return
    key = (run_id, stream)
    raw = _pending_agent_logs.pop(key, "") + (chunk or "")
    if "\n" in raw:
        complete, sep, rest = raw.rpartition("\n")
        _emit_agent_log_chunk(
            run_id, stream, sanitize_log_text(complete + sep, token)
        )
        raw = rest
    raw = _emit_sanitized_prefix(run_id, stream, raw, token)
    if raw:
        _pending_agent_logs[key] = raw
