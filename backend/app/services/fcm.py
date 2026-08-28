import os
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, messaging

from app.config import ROOT


def _ensure_app() -> None:
    if firebase_admin._apps:
        return
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not path:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS is not set")
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = ROOT / path
    firebase_admin.initialize_app(credentials.Certificate(str(resolved)))


def send_push(
    token: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> str:
    _ensure_app()
    payload = {"title": title, "body": body}
    if data:
        payload.update({key: str(value) for key, value in data.items()})
    message = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        data=payload,
        token=token,
    )
    return messaging.send(message)
