from datetime import datetime, timedelta, timezone
import uuid

import pyotp
from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models import ApprovalGate, AuditEvent, Device, SandboxRun
from app.services.approval import notify_devices_of_approval_gate
from app.services.events import notify_run_event
from app.services.totp import new_secret


client = TestClient(app)
API_HEADERS = {"X-API-Key": "dev-local-key"}
ENROLLMENT_SECRET = "dev-enrollment-secret"
ENROLL_HEADERS = {
    "X-API-Key": "dev-local-key",
    "X-Device-Enrollment-Secret": ENROLLMENT_SECRET,
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


def _insert_device(
    device_id: str,
    secret: str,
    *,
    fcm_token: str = "existing-token",
    label: str = "existing",
    revoked: bool = False,
) -> None:
    db = SessionLocal()
    try:
        device = Device(
            device_id=device_id,
            fcm_token=fcm_token,
            totp_secret=secret,
            label=label,
        )
        if revoked:
            device.revoked_at = datetime.now(timezone.utc)
        db.add(device)
        db.commit()
    finally:
        db.close()


def _insert_run_with_pending_gate() -> tuple[int, str]:
    db = SessionLocal()
    try:
        run = SandboxRun(status="queued", repo="a/b", ref="main")
        db.add(run)
        db.commit()
        db.refresh(run)
        gate = ApprovalGate(
            run_id=run.id,
            gate="sandbox_provision",
            status="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=90),
        )
        db.add(gate)
        db.commit()
        return run.id, gate.gate
    finally:
        db.close()


def test_revoke_requires_api_key():
    response = client.post("/v1/devices/missing/revoke")
    assert response.status_code == 401
    assert "totp_secret" not in response.json()


def test_revoke_does_not_require_enrollment_secret(monkeypatch):
    _enroll_secret(monkeypatch)
    device_id = _device_id("revoke-no-enroll")
    secret = new_secret()
    _insert_device(device_id, secret)
    response = client.post(
        f"/v1/devices/{device_id}/revoke",
        headers=API_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["device_id"] == device_id
    assert "totp_secret" not in body
    assert "secret" not in body
    stored = _stored_device(device_id)
    assert stored is not None
    assert stored.revoked_at is not None
    assert stored.totp_secret == secret


def test_revoke_unknown_device_is_not_found():
    response = client.post(
        "/v1/devices/does-not-exist/revoke",
        headers=API_HEADERS,
    )
    assert response.status_code == 404
    assert "totp_secret" not in response.json()


def test_revoke_active_device_succeeds():
    device_id = _device_id("revoke-active")
    secret = new_secret()
    _insert_device(device_id, secret)
    response = client.post(
        f"/v1/devices/{device_id}/revoke",
        headers=API_HEADERS,
    )
    assert response.status_code == 200
    stored = _stored_device(device_id)
    assert stored is not None
    assert stored.revoked_at is not None
    assert stored.totp_secret == secret


def test_revoke_is_idempotent():
    device_id = _device_id("revoke-twice")
    secret = new_secret()
    _insert_device(device_id, secret)
    first = client.post(
        f"/v1/devices/{device_id}/revoke",
        headers=API_HEADERS,
    )
    assert first.status_code == 200
    first_revoked = _stored_device(device_id).revoked_at
    second = client.post(
        f"/v1/devices/{device_id}/revoke",
        headers=API_HEADERS,
    )
    assert second.status_code == 200
    stored = _stored_device(device_id)
    assert stored.revoked_at == first_revoked
    assert stored.totp_secret == secret


def test_revoked_device_cannot_approve_with_valid_otp():
    device_id = _device_id("revoke-approve")
    secret = new_secret()
    _insert_device(device_id, secret, revoked=True)
    run_id, _gate = _insert_run_with_pending_gate()
    response = client.post(
        f"/v1/sandbox/runs/{run_id}/approval",
        headers=API_HEADERS,
        json={"device_id": device_id, "otp_code": pyotp.TOTP(secret).now()},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "device revoked"
    assert "totp_secret" not in response.json()


def test_revoked_device_cannot_reject_with_valid_otp():
    device_id = _device_id("revoke-reject")
    secret = new_secret()
    _insert_device(device_id, secret, revoked=True)
    run_id, _gate = _insert_run_with_pending_gate()
    response = client.post(
        f"/v1/sandbox/runs/{run_id}/rejection",
        headers=API_HEADERS,
        json={"device_id": device_id, "otp_code": pyotp.TOTP(secret).now()},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "device revoked"


def test_revoked_device_cannot_pause_resume_or_kill():
    device_id = _device_id("revoke-control")
    secret = new_secret()
    _insert_device(device_id, secret, revoked=True)
    db = SessionLocal()
    try:
        run = SandboxRun(
            status="paused",
            repo="a/b",
            ref="main",
            control_state="paused",
            e2b_sandbox_id="sbx-1",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()
    code = pyotp.TOTP(secret).now()
    for action in ("pause", "resume", "kill"):
        response = client.post(
            f"/v1/sandbox/runs/{run_id}/{action}",
            headers=API_HEADERS,
            json={"device_id": device_id, "otp_code": code},
        )
        assert response.status_code == 403, action
        assert response.json()["detail"] == "device revoked"


def test_active_device_can_still_approve(monkeypatch):
    device_id = _device_id("revoke-still-ok")
    secret = new_secret()
    _insert_device(device_id, secret)
    run_id, _gate = _insert_run_with_pending_gate()
    delayed = []

    class Result:
        id = "task"

    monkeypatch.setattr(
        "app.routers.sandbox.clone_and_index.delay",
        lambda run_id: delayed.append(run_id) or Result(),
    )
    response = client.post(
        f"/v1/sandbox/runs/{run_id}/approval",
        headers=API_HEADERS,
        json={"device_id": device_id, "otp_code": pyotp.TOTP(secret).now()},
    )
    assert response.status_code == 200
    assert delayed == [run_id]


def test_revoked_registration_cannot_reactivate(monkeypatch):
    _enroll_secret(monkeypatch)
    device_id = _device_id("revoke-rereg")
    secret = new_secret()
    _insert_device(
        device_id,
        secret,
        fcm_token="old-token",
        label="old-label",
        revoked=True,
    )
    response = client.post(
        "/v1/devices/register",
        json={
            "device_id": device_id,
            "fcm_token": "new-token",
            "label": "new-label",
        },
        headers=ENROLL_HEADERS,
    )
    assert response.status_code == 403
    body = response.json()
    assert body["detail"] == "device revoked"
    assert "totp_secret" not in body
    stored = _stored_device(device_id)
    assert stored is not None
    assert stored.revoked_at is not None
    assert stored.fcm_token == "old-token"
    assert stored.label == "old-label"
    assert stored.totp_secret == secret


def test_approval_fcm_skips_revoked_device(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.services.approval.fcm.send_push_with_timeout",
        lambda token, title, body, data=None: sent.append(token) or "ok",
    )
    active_id = _device_id("fcm-active")
    revoked_id = _device_id("fcm-revoked")
    _insert_device(active_id, new_secret(), fcm_token="active-fcm")
    _insert_device(
        revoked_id,
        new_secret(),
        fcm_token="revoked-fcm",
        revoked=True,
    )
    db = SessionLocal()
    try:
        run = SandboxRun(status="queued", repo="owner/repo", ref="main")
        db.add(run)
        db.commit()
        db.refresh(run)
        gate = ApprovalGate(
            run_id=run.id,
            gate="sandbox_provision",
            status="pending",
        )
        notify_devices_of_approval_gate(db, run, gate)
    finally:
        db.close()
    assert "active-fcm" in sent
    assert "revoked-fcm" not in sent


def test_run_event_fcm_skips_revoked_device(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.services.events.fcm.send_push_with_timeout",
        lambda token, title, body, data=None: sent.append(token) or "ok",
    )
    monkeypatch.setattr(
        "app.services.events.publish_run_update",
        lambda payload=None: None,
    )
    active_id = _device_id("evt-active")
    revoked_id = _device_id("evt-revoked")
    _insert_device(active_id, new_secret(), fcm_token="active-event-fcm")
    _insert_device(
        revoked_id,
        new_secret(),
        fcm_token="revoked-event-fcm",
        revoked=True,
    )
    db = SessionLocal()
    try:
        run = SandboxRun(status="queued", repo="owner/repo", ref="main")
        db.add(run)
        db.commit()
        db.refresh(run)
        notify_run_event(db, run, "title", "body")
    finally:
        db.close()
    assert "active-event-fcm" in sent
    assert "revoked-event-fcm" not in sent


def test_test_push_rejects_revoked_device(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.routers.devices.fcm.send_push",
        lambda *args, **kwargs: sent.append(args) or "ok",
    )
    device_id = _device_id("push-revoked")
    _insert_device(device_id, new_secret(), revoked=True)
    response = client.post(
        f"/v1/devices/{device_id}/test-push",
        headers=API_HEADERS,
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "device revoked"
    assert "totp_secret" not in response.json()
    assert sent == []


def test_revoke_audit_does_not_record_secrets():
    device_id = _device_id("revoke-audit")
    secret = new_secret()
    _insert_device(device_id, secret)
    response = client.post(
        f"/v1/devices/{device_id}/revoke",
        headers=API_HEADERS,
    )
    assert response.status_code == 200
    db = SessionLocal()
    try:
        events = (
            db.query(AuditEvent)
            .filter(
                AuditEvent.device_id == device_id,
                AuditEvent.action == "device_revoke",
            )
            .all()
        )
        assert events
        event = events[-1]
        assert event.actor == "human"
        assert event.result == "success"
        blob = f"{event.event_metadata}{event.detail}{event.action}"
        assert secret not in blob
        assert ENROLLMENT_SECRET not in blob
        assert "totp_secret" not in blob
        assert "enrollment" not in blob.lower()
    finally:
        db.close()
