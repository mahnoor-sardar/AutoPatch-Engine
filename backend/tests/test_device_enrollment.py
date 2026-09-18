import uuid

from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models import AuditEvent, Device
from app.services.totp import new_secret, verify_code
import pyotp


client = TestClient(app)
API_HEADERS = {"X-API-Key": "dev-local-key"}
ENROLLMENT_SECRET = "dev-enrollment-secret"
ENROLL_HEADERS = {
    "X-API-Key": "dev-local-key",
    "X-Device-Enrollment-Secret": ENROLLMENT_SECRET,
}
REGISTER_BODY = {
    "fcm_token": "fcm-test-token",
    "label": "Pixel Test",
}


def _enroll_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "device_enrollment_secret", ENROLLMENT_SECRET)


def _device_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _stored_device(device_id: str) -> Device | None:
    db = SessionLocal()
    try:
        return (
            db.query(Device)
            .filter(Device.device_id == device_id)
            .one_or_none()
        )
    finally:
        db.close()


def _insert_device(device_id: str, secret: str) -> None:
    db = SessionLocal()
    try:
        db.add(
            Device(
                device_id=device_id,
                fcm_token="existing-token",
                totp_secret=secret,
                label="existing",
            )
        )
        db.commit()
    finally:
        db.close()


def test_api_key_only_cannot_create_device_or_totp(monkeypatch):
    _enroll_secret(monkeypatch)
    device_id = _device_id("f01-api-only-new")
    response = client.post(
        "/v1/devices/register",
        json={"device_id": device_id, **REGISTER_BODY},
        headers=API_HEADERS,
    )
    assert response.status_code == 401
    body = response.json()
    assert "totp_secret" not in body
    assert _stored_device(device_id) is None


def test_api_key_only_cannot_reregister_and_steal_totp(monkeypatch):
    _enroll_secret(monkeypatch)
    device_id = _device_id("f01-api-only-existing")
    secret = new_secret()
    _insert_device(device_id, secret)
    response = client.post(
        "/v1/devices/register",
        json={"device_id": device_id, **REGISTER_BODY},
        headers=API_HEADERS,
    )
    assert response.status_code == 401
    body = response.json()
    assert "totp_secret" not in body
    stored = _stored_device(device_id)
    assert stored is not None
    assert stored.totp_secret == secret
    assert stored.fcm_token == "existing-token"


def test_wrong_enrollment_secret_cannot_manufacture_identity(monkeypatch):
    _enroll_secret(monkeypatch)
    device_id = _device_id("f01-wrong-enroll")
    response = client.post(
        "/v1/devices/register",
        json={"device_id": device_id, **REGISTER_BODY},
        headers={
            "X-API-Key": "dev-local-key",
            "X-Device-Enrollment-Secret": "not-the-enrollment-secret",
        },
    )
    assert response.status_code == 401
    assert "totp_secret" not in response.json()
    assert _stored_device(device_id) is None


def test_legitimate_enrollment_issues_totp_once(monkeypatch):
    _enroll_secret(monkeypatch)
    device_id = _device_id("f01-legit-new")
    response = client.post(
        "/v1/devices/register",
        json={"device_id": device_id, **REGISTER_BODY},
        headers=ENROLL_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["device_id"] == device_id
    secret = body["totp_secret"]
    assert secret
    assert verify_code(secret, pyotp.TOTP(secret).now())
    stored = _stored_device(device_id)
    assert stored is not None
    assert stored.totp_secret == secret
    assert stored.fcm_token == REGISTER_BODY["fcm_token"]


def test_legitimate_reregister_updates_push_without_returning_totp(monkeypatch):
    _enroll_secret(monkeypatch)
    device_id = _device_id("f01-legit-existing")
    secret = new_secret()
    _insert_device(device_id, secret)
    response = client.post(
        "/v1/devices/register",
        json={
            "device_id": device_id,
            "fcm_token": "rotated-fcm",
            "label": "updated-label",
        },
        headers=ENROLL_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["device_id"] == device_id
    assert "totp_secret" not in body
    stored = _stored_device(device_id)
    assert stored is not None
    assert stored.totp_secret == secret
    assert stored.fcm_token == "rotated-fcm"
    assert stored.label == "updated-label"


def test_enrollment_audit_does_not_record_totp_or_enrollment_secret(monkeypatch):
    _enroll_secret(monkeypatch)
    device_id = _device_id("f01-audit")
    response = client.post(
        "/v1/devices/register",
        json={"device_id": device_id, **REGISTER_BODY},
        headers=ENROLL_HEADERS,
    )
    assert response.status_code == 200
    issued = response.json()["totp_secret"]
    db = SessionLocal()
    try:
        events = (
            db.query(AuditEvent)
            .filter(
                AuditEvent.device_id == device_id,
                AuditEvent.action == "device_register",
            )
            .all()
        )
        assert len(events) == 1
        event = events[0]
        assert event.actor == "android"
        assert event.result == "success"
        blob = str(event.event_metadata) + str(event.detail)
        assert issued not in blob
        assert ENROLLMENT_SECRET not in blob
        assert "totp_secret" not in blob
    finally:
        db.close()


def test_sandbox_list_still_works_with_api_key_only(monkeypatch):
    _enroll_secret(monkeypatch)
    response = client.get("/v1/sandbox/runs", headers=API_HEADERS)
    assert response.status_code == 200
    assert "runs" in response.json()
