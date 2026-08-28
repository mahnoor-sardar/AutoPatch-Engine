import hashlib
import hmac
import time

from sqlalchemy.orm import Session

from app.models import AuditEvent, Device
from app.services import totp

TOKEN_TTL_SECONDS = 90


def verify_device_authorization(
    device: Device,
    otp_code: str | None,
    approval_token: str | None = None,
    token_ts: int | None = None,
    payload: str = "",
) -> bool:
    if device is None or not device.totp_secret:
        return False

    if otp_code and totp.verify_code(device.totp_secret, otp_code):
        return True

    if approval_token and token_ts is not None:
        now = int(time.time())
        if abs(now - int(token_ts)) > TOKEN_TTL_SECONDS:
            return False
        expected = hmac.new(
            device.totp_secret.encode("utf-8"),
            f"{payload}|{token_ts}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, approval_token)

    return False


def make_approval_token(secret: str, payload: str, token_ts: int) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        f"{payload}|{token_ts}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


ACTOR_ANDROID = "android"
ACTOR_WORKER = "worker"
ACTOR_SYSTEM = "system"
ACTOR_GITHUB = "github"
ACTOR_WEBHOOK = "webhook"
ACTOR_HUMAN = "human"

RESULT_SUCCESS = "success"
RESULT_FAILURE = "failure"
RESULT_DENIED = "denied"
RESULT_EXPIRED = "expired"
RESULT_REJECTED = "rejected"

_SENSITIVE_META_KEYS = frozenset(
    {
        "otp",
        "otp_code",
        "totp",
        "totp_secret",
        "approval_token",
        "token",
        "token_ts",
        "api_key",
        "secret",
        "password",
        "authorization",
        "fcm_token",
    }
)


def _safe_metadata(event_metadata: dict | None) -> dict | None:
    if not event_metadata:
        return None
    cleaned = {}
    for key, value in event_metadata.items():
        lowered = str(key).lower()
        if lowered in _SENSITIVE_META_KEYS:
            continue
        if "secret" in lowered or "token" in lowered or "password" in lowered:
            continue
        cleaned[key] = value
    return cleaned or None


def log_audit(
    db: Session,
    action: str,
    run_id: int | None = None,
    device_id: str | None = None,
    detail: str | None = None,
    *,
    actor: str | None = None,
    result: str | None = None,
    event_metadata: dict | None = None,
    commit: bool = False,
) -> AuditEvent:
    """Attach an audit row to ``db``. The caller commits unless ``commit=True``."""
    event = AuditEvent(
        run_id=run_id,
        device_id=device_id,
        action=action,
        actor=actor,
        result=result,
        detail=detail,
        event_metadata=_safe_metadata(event_metadata),
    )
    db.add(event)
    if commit:
        db.commit()
    return event
