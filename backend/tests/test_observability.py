import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_db
from app.main import app
from app.models import ErrorIngest

client = TestClient(app)

SENTRY_SECRET = "sentry-test-secret"
DATADOG_SECRET = "datadog-test-secret"

PYTHON_TRACE = (
    "Traceback (most recent call last):\n"
    '  File "app/services/user.py", line 42, in get_user\n'
    "    return user.name\n"
    "AttributeError: 'NoneType' object has no attribute 'name'\n"
)

SENTRY_PAYLOAD = {
    "event": {
        "exception": {
            "values": [
                {
                    "type": "AttributeError",
                    "value": "'NoneType' object has no attribute 'name'",
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "app/services/user.py",
                                "lineno": 42,
                                "function": "get_user",
                                "context_line": "return user.name",
                            }
                        ]
                    },
                }
            ]
        }
    }
}

DATADOG_PAYLOAD = {
    "error": {
        "stack": PYTHON_TRACE,
    }
}


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _override_secrets(monkeypatch) -> None:
    monkeypatch.setattr(settings, "sentry_webhook_secret", SENTRY_SECRET)
    monkeypatch.setattr(settings, "datadog_webhook_secret", DATADOG_SECRET)


class FakeDB:
    def __init__(self) -> None:
        self.added: list[ErrorIngest] = []

    def add(self, obj: ErrorIngest) -> None:
        obj.id = 1
        self.added.append(obj)

    def commit(self) -> None:
        return None

    def refresh(self, obj: ErrorIngest) -> None:
        if obj.id is None:
            obj.id = 1


def _override_db() -> FakeDB:
    fake = FakeDB()
    app.dependency_overrides[get_db] = lambda: fake
    return fake


def test_sentry_rejects_missing_signature(monkeypatch):
    _override_secrets(monkeypatch)
    body = json.dumps(SENTRY_PAYLOAD).encode()
    response = client.post("/v1/webhooks/sentry", content=body)
    assert response.status_code == 401


def test_sentry_rejects_invalid_signature(monkeypatch):
    _override_secrets(monkeypatch)
    body = json.dumps(SENTRY_PAYLOAD).encode()
    response = client.post(
        "/v1/webhooks/sentry",
        content=body,
        headers={"Sentry-Hook-Signature": "deadbeef"},
    )
    assert response.status_code == 401


def test_datadog_rejects_invalid_signature(monkeypatch):
    _override_secrets(monkeypatch)
    body = json.dumps(DATADOG_PAYLOAD).encode()
    response = client.post(
        "/v1/webhooks/datadog",
        content=body,
        headers={"X-Datadog-Signature": "sha256=deadbeef"},
    )
    assert response.status_code == 401


def test_sentry_accepts_sentry_hook_signature(monkeypatch):
    _override_secrets(monkeypatch)
    fake = _override_db()
    body = json.dumps(SENTRY_PAYLOAD).encode()

    try:
        response = client.post(
            "/v1/webhooks/sentry",
            content=body,
            headers={"Sentry-Hook-Signature": _sign(body, SENTRY_SECRET)},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["provider"] == "sentry"
        assert payload["id"] == 1
        assert payload["exception_type"] == "AttributeError"
        assert payload["frames"][0]["file"] == "app/services/user.py"
        assert payload["frames"][0]["line"] == 42
        assert payload["frames"][0]["function"] == "get_user"
        assert len(fake.added) == 1
        assert fake.added[0].provider == "sentry"
        assert "app/services/user.py" in fake.added[0].stack_trace
    finally:
        app.dependency_overrides.clear()


def test_sentry_accepts_x_sentry_hook_signature(monkeypatch):
    _override_secrets(monkeypatch)
    _override_db()
    body = json.dumps(SENTRY_PAYLOAD).encode()

    try:
        response = client.post(
            "/v1/webhooks/sentry",
            content=body,
            headers={"X-Sentry-Hook-Signature": _sign(body, SENTRY_SECRET)},
        )
        assert response.status_code == 200
        assert response.json()["provider"] == "sentry"
    finally:
        app.dependency_overrides.clear()


def test_datadog_accepts_valid_signature(monkeypatch):
    _override_secrets(monkeypatch)
    fake = _override_db()
    body = json.dumps(DATADOG_PAYLOAD).encode()
    digest = _sign(body, DATADOG_SECRET)

    try:
        response = client.post(
            "/v1/webhooks/datadog",
            content=body,
            headers={"X-Datadog-Signature": f"sha256={digest}"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["provider"] == "datadog"
        assert payload["exception_type"] == "AttributeError"
        assert payload["frames"][0]["function"] == "get_user"
        assert fake.added[0].provider == "datadog"
        assert fake.added[0].stack_trace == PYTHON_TRACE
    finally:
        app.dependency_overrides.clear()


def test_valid_signature_rejects_malformed_json(monkeypatch):
    _override_secrets(monkeypatch)
    body = b"{not-json"

    response = client.post(
        "/v1/webhooks/sentry",
        content=body,
        headers={"Sentry-Hook-Signature": _sign(body, SENTRY_SECRET)},
    )
    assert response.status_code == 400


def test_valid_signature_rejects_payload_without_stack_trace(monkeypatch):
    _override_secrets(monkeypatch)
    body = json.dumps({"event": {"message": "no stack"}}).encode()

    response = client.post(
        "/v1/webhooks/datadog",
        content=body,
        headers={"X-Datadog-Signature": _sign(body, DATADOG_SECRET)},
    )
    assert response.status_code == 400
