import hashlib
import hmac
import time

from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditEvent, Device, DeviceAuthReplay
from app.services import totp

TOKEN_TTL_SECONDS = 90
AUTH_REPLAY_TTL_SECONDS = 120

AuthFactor = Literal["otp", "token"]


def device_auth_factor(
    device: Device,
    otp_code: str | None,
    approval_token: str | None = None,
    token_ts: int | None = None,
    payload: str = "",
) -> AuthFactor | None:
    if device is None or not device.totp_secret:
        return None

    if otp_code and totp.verify_code(device.totp_secret, otp_code):
        return "otp"

    if approval_token and token_ts is not None:
        now = int(time.time())
        if abs(now - int(token_ts)) > TOKEN_TTL_SECONDS:
            return None
        expected = hmac.new(
            device.totp_secret.encode("utf-8"),
            f"{payload}|{token_ts}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if hmac.compare_digest(expected, approval_token):
            return "token"

    return None


def verify_device_authorization(
    device: Device,
    otp_code: str | None,
    approval_token: str | None = None,
    token_ts: int | None = None,
    payload: str = "",
) -> bool:
    return (
        device_auth_factor(
            device,
            otp_code,
            approval_token,
            token_ts,
            payload,
        )
        is not None
    )


def _auth_fingerprint(
    device: Device,
    payload: str,
    otp_code: str | None,
    approval_token: str | None,
    auth_factor: AuthFactor | None,
) -> str | None:
    secret = (device.totp_secret or "").encode("utf-8")
    if not secret or not auth_factor:
        return None
    if auth_factor == "otp":
        if not otp_code:
            return None
        material = f"{payload}|otp|{otp_code}".encode("utf-8")
    elif auth_factor == "token":
        if not approval_token:
            return None
        material = f"{payload}|tok|{approval_token}".encode("utf-8")
    else:
        return None
    return hmac.new(secret, material, hashlib.sha256).hexdigest()


def consume_device_authorization(
    db: Session,
    device: Device,
    payload: str,
    otp_code: str | None,
    approval_token: str | None = None,
    *,
    auth_factor: AuthFactor | None,
) -> bool:
    """Record a one-time use of the credential that authorized this action.

    ``auth_factor`` must be the factor that already passed verification.
    Returns False if the same credential was already used for the same
    action_key (payload). Does not store the raw OTP or token.
    """
    digest = _auth_fingerprint(
        device,
        payload,
        otp_code,
        approval_token,
        auth_factor,
    )
    if digest is None:
        return False
    action_key = payload[:256]
    query = db.query(DeviceAuthReplay).filter(
        DeviceAuthReplay.device_id == device.device_id,
        DeviceAuthReplay.action_key == action_key,
        DeviceAuthReplay.credential_hash == digest,
    )
    if hasattr(query, "with_for_update"):
        query = query.with_for_update()
    existing = query.one_or_none()
    if existing is not None:
        created = existing.created_at or datetime.now(timezone.utc)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - created
        if age < timedelta(seconds=AUTH_REPLAY_TTL_SECONDS):
            return False
        db.delete(existing)
    db.add(
        DeviceAuthReplay(
            device_id=device.device_id,
            action_key=action_key,
            credential_hash=digest,
        )
    )
    flush = getattr(db, "flush", None)
    if flush is None:
        return True
    try:
        flush()
    except IntegrityError:
        return False
    return True


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
        "enrollment_secret",
        "device_enrollment_secret",
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
