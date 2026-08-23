import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.github_app import verify_webhook_signature

client = TestClient(app)


def test_verify_webhook_signature_accepts_valid():
    body = b'{"zen":"ok"}'
    secret = "test-secret"
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, secret, f"sha256={digest}")


def test_verify_webhook_signature_rejects_invalid():
    assert not verify_webhook_signature(b"{}", "secret", "sha256=deadbeef")


def test_webhook_rejects_bad_signature():
    response = client.post(
        "/v1/github/webhook",
        content=b"{}",
        headers={"X-Hub-Signature-256": "sha256=nope", "X-GitHub-Event": "ping"},
    )
    assert response.status_code == 401


def test_webhook_ping_ok():
    body = json.dumps({"zen": "ok"}).encode()
    digest = hmac.new(settings.github_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    response = client.post(
        "/v1/github/webhook",
        content=body,
        headers={"X-Hub-Signature-256": f"sha256={digest}", "X-GitHub-Event": "ping"},
    )
    assert response.status_code == 200
    assert response.json()["event"] == "ping"
