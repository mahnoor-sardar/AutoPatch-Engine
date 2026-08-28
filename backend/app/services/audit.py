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


def log_audit(
    db: Session,
    action: str,
    run_id: int | None = None,
    device_id: str | None = None,
    detail: str | None = None,
) -> None:
    db.add(
        AuditEvent(
            run_id=run_id,
            device_id=device_id,
            action=action,
            detail=detail,
        )
    )
    db.commit()
