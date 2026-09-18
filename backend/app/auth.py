import hashlib
import hmac
import secrets
import time

from fastapi import Header, HTTPException

from app.config import settings

WS_TICKET_TTL_SECONDS = 90
WS_TICKET_PREFIX = "autopatch."
_WS_TICKET_MESSAGE = "ws-ticket"
# Long-lived X-API-Key on the WebSocket upgrade is local/dev/test tooling only.
_WS_API_KEY_HEADER_ENVS = frozenset({"local", "dev", "development", "test"})


def secrets_match(provided: str | None, expected: str | None) -> bool:
    if not provided or not expected:
        return False
    try:
        return secrets.compare_digest(provided, expected)
    except (TypeError, ValueError):
        return False


def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    if not secrets_match(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="invalid api key")


def ws_api_key_header_allowed() -> bool:
    """True when the WS upgrade may use X-API-Key (non-browser/dev only)."""
    return settings.app_env.lower() in _WS_API_KEY_HEADER_ENVS


def require_device_enrollment(
    x_device_enrollment_secret: str | None = Header(
        default=None,
        alias="X-Device-Enrollment-Secret",
    ),
) -> None:
    if not secrets_match(
        x_device_enrollment_secret,
        settings.device_enrollment_secret,
    ):
        raise HTTPException(status_code=401, detail="invalid enrollment secret")


def issue_ws_ticket(now: int | None = None) -> tuple[str, int]:
    issued_at = int(now if now is not None else time.time())
    signature = _ws_ticket_signature(issued_at)
    return f"{issued_at}.{signature}", WS_TICKET_TTL_SECONDS


def verify_ws_ticket(ticket: str | None, now: int | None = None) -> bool:
    if not ticket or "." not in ticket:
        return False
    ts_raw, signature = ticket.split(".", 1)
    try:
        issued_at = int(ts_raw)
    except (TypeError, ValueError):
        return False
    moment = int(now if now is not None else time.time())
    if moment - issued_at > WS_TICKET_TTL_SECONDS or issued_at > moment + 5:
        return False
    expected = _ws_ticket_signature(issued_at)
    if not signature or not expected:
        return False
    return secrets_match(signature, expected)


def ws_subprotocol_for_ticket(ticket: str) -> str:
    return f"{WS_TICKET_PREFIX}{ticket}"


def ticket_from_ws_protocols(header: str | None) -> str | None:
    if not header:
        return None
    for part in header.split(","):
        offered = part.strip()
        if offered.startswith(WS_TICKET_PREFIX):
            ticket = offered[len(WS_TICKET_PREFIX) :]
            return ticket or None
    return None


def _ws_ticket_signature(issued_at: int) -> str:
    key = (settings.api_key or "").encode("utf-8")
    message = f"{_WS_TICKET_MESSAGE}|{issued_at}".encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()
