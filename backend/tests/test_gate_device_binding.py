from datetime import datetime, timedelta, timezone
import uuid

import pyotp
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models import ApprovalGate, Device, SandboxRun
from app.services.approval import (
    ApprovalDeviceUnavailable,
    apply_gate_expiry,
    create_pending_gate,
    notify_devices_of_approval_gate,
    try_claim_pending_gate,
)
from app.services.totp import new_secret


client = TestClient(app)
API_HEADERS = {"X-API-Key": "dev-local-key"}


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _insert_device(
    device_id: str,
    secret: str | None,
    *,
    fcm_token: str = "fcm",
    revoked: bool = False,
) -> None:
    db = SessionLocal()
    try:
        device = Device(
            device_id=device_id,
            fcm_token=fcm_token,
            totp_secret=secret,
            label=device_id,
        )
        if revoked:
            device.revoked_at = datetime.now(timezone.utc)
        db.add(device)
        db.commit()
    finally:
        db.close()


def _insert_run_and_gate(device_id: str | None) -> tuple[int, int]:
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
            device_id=device_id,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=90),
        )
        db.add(gate)
        db.commit()
        db.refresh(gate)
        return run.id, gate.id
    finally:
        db.close()


def _gate(gate_id: int) -> ApprovalGate:
    db = SessionLocal()
    try:
        return db.query(ApprovalGate).filter(ApprovalGate.id == gate_id).one()
    finally:
        db.close()


def test_bound_device_can_approve_other_device_cannot(monkeypatch):
    device_a = _id("bind-a")
    device_b = _id("bind-b")
    secret_a = new_secret()
    secret_b = new_secret()
    _insert_device(device_a, secret_a)
    _insert_device(device_b, secret_b)
    monkeypatch.setattr(settings, "approval_device_id", device_a)
    run_id, gate_id = _insert_run_and_gate(device_a)
    delayed = []
    monkeypatch.setattr(
        "app.routers.sandbox.clone_and_index.delay",
        lambda run_id: delayed.append(run_id) or type("R", (), {"id": "t"})(),
    )
    denied = client.post(
        f"/v1/sandbox/runs/{run_id}/approval",
        headers=API_HEADERS,
        json={"device_id": device_b, "otp_code": pyotp.TOTP(secret_b).now()},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "device is not authorized for this gate"
    stored = _gate(gate_id)
    assert stored.status == "pending"
    assert stored.device_id == device_a
    allowed = client.post(
        f"/v1/sandbox/runs/{run_id}/approval",
        headers=API_HEADERS,
        json={"device_id": device_a, "otp_code": pyotp.TOTP(secret_a).now()},
    )
    assert allowed.status_code == 200
    assert _gate(gate_id).status == "approved"
    assert _gate(gate_id).device_id == device_a


def test_bound_device_can_reject_other_device_cannot():
    device_a = _id("rej-a")
    device_b = _id("rej-b")
    secret_a = new_secret()
    secret_b = new_secret()
    _insert_device(device_a, secret_a)
    _insert_device(device_b, secret_b)
    run_id, gate_id = _insert_run_and_gate(device_a)
    denied = client.post(
        f"/v1/sandbox/runs/{run_id}/rejection",
        headers=API_HEADERS,
        json={"device_id": device_b, "otp_code": pyotp.TOTP(secret_b).now()},
    )
    assert denied.status_code == 403
    assert _gate(gate_id).status == "pending"
    assert _gate(gate_id).device_id == device_a
    allowed = client.post(
        f"/v1/sandbox/runs/{run_id}/rejection",
        headers=API_HEADERS,
        json={"device_id": device_a, "otp_code": pyotp.TOTP(secret_a).now()},
    )
    assert allowed.status_code == 200
    assert _gate(gate_id).status == "rejected"
    assert _gate(gate_id).device_id == device_a


def test_pending_list_only_returns_caller_bound_gates():
    device_a = _id("list-a")
    device_b = _id("list-b")
    _insert_device(device_a, new_secret())
    _insert_device(device_b, new_secret())
    run_a, _ = _insert_run_and_gate(device_a)
    _insert_run_and_gate(device_b)
    _insert_run_and_gate(None)
    listed_a = client.get(
        "/v1/sandbox/approvals/pending",
        headers=API_HEADERS,
        params={"device_id": device_a},
    )
    assert listed_a.status_code == 200
    run_ids_a = {item["run_id"] for item in listed_a.json()["approvals"]}
    assert run_a in run_ids_a
    listed_b = client.get(
        "/v1/sandbox/approvals/pending",
        headers=API_HEADERS,
        params={"device_id": device_b},
    )
    run_ids_b = {item["run_id"] for item in listed_b.json()["approvals"]}
    assert run_a not in run_ids_b


def test_pending_list_does_not_include_null_device_gates():
    device_a = _id("list-null-a")
    _insert_device(device_a, new_secret())
    run_null, _ = _insert_run_and_gate(None)
    listed = client.get(
        "/v1/sandbox/approvals/pending",
        headers=API_HEADERS,
        params={"device_id": device_a},
    )
    assert listed.status_code == 200
    assert run_null not in {item["run_id"] for item in listed.json()["approvals"]}


def test_pending_list_rejects_unknown_and_revoked_devices():
    missing = client.get(
        "/v1/sandbox/approvals/pending",
        headers=API_HEADERS,
        params={"device_id": _id("missing")},
    )
    assert missing.status_code == 404
    revoked_id = _id("list-revoked")
    _insert_device(revoked_id, new_secret(), revoked=True)
    revoked = client.get(
        "/v1/sandbox/approvals/pending",
        headers=API_HEADERS,
        params={"device_id": revoked_id},
    )
    assert revoked.status_code == 403


def test_create_pending_gate_binds_configured_device(monkeypatch):
    device_id = _id("create-bind")
    _insert_device(device_id, new_secret())
    monkeypatch.setattr(settings, "approval_device_id", device_id)
    db = SessionLocal()
    try:
        run = SandboxRun(status="queued", repo="a/b", ref="main")
        db.add(run)
        db.commit()
        db.refresh(run)
        gate = create_pending_gate(db, run, "sandbox_provision", notify=False)
        assert gate.device_id == device_id
        assert gate.status == "pending"
        assert gate.device_id is not None
    finally:
        db.close()


def test_create_pending_gate_fails_if_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "approval_device_id", None)
    db = SessionLocal()
    try:
        run = SandboxRun(status="queued", repo="a/b", ref="main")
        db.add(run)
        db.commit()
        db.refresh(run)
        try:
            create_pending_gate(db, run, "sandbox_provision", notify=False)
            raise AssertionError("missing approval device must fail closed")
        except ApprovalDeviceUnavailable as exc:
            assert "not configured" in exc.detail
        pending = (
            db.query(ApprovalGate)
            .filter(ApprovalGate.run_id == run.id, ApprovalGate.status == "pending")
            .all()
        )
        assert pending == []
    finally:
        db.close()


def test_create_pending_gate_fails_for_unknown_revoked_and_secretless_device(
    monkeypatch,
):
    db = SessionLocal()
    try:
        run = SandboxRun(status="queued", repo="a/b", ref="main")
        db.add(run)
        db.commit()
        db.refresh(run)

        monkeypatch.setattr(settings, "approval_device_id", _id("missing-cfg"))
        try:
            create_pending_gate(db, run, "sandbox_provision", notify=False)
            raise AssertionError("unknown device must fail closed")
        except ApprovalDeviceUnavailable:
            pass

        revoked_id = _id("cfg-revoked")
        _insert_device(revoked_id, new_secret(), revoked=True)
        monkeypatch.setattr(settings, "approval_device_id", revoked_id)
        try:
            create_pending_gate(db, run, "sandbox_provision", notify=False)
            raise AssertionError("revoked device must fail closed")
        except ApprovalDeviceUnavailable as exc:
            assert "revoked" in exc.detail

        secretless = _id("cfg-secretless")
        _insert_device(secretless, None)
        monkeypatch.setattr(settings, "approval_device_id", secretless)
        try:
            create_pending_gate(db, run, "sandbox_provision", notify=False)
            raise AssertionError("device without TOTP must fail closed")
        except ApprovalDeviceUnavailable:
            pass

        pending = (
            db.query(ApprovalGate)
            .filter(ApprovalGate.run_id == run.id, ApprovalGate.status == "pending")
            .all()
        )
        assert pending == []
    finally:
        db.close()


def test_approval_notification_targets_only_bound_device(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.services.approval.fcm.send_push_with_timeout",
        lambda token, title, body, data=None: sent.append(token) or "ok",
    )
    bound_id = _id("notify-bound")
    other_id = _id("notify-other")
    _insert_device(bound_id, new_secret(), fcm_token="bound-fcm")
    _insert_device(other_id, new_secret(), fcm_token="other-fcm")
    db = SessionLocal()
    try:
        run = SandboxRun(status="queued", repo="owner/repo", ref="main")
        db.add(run)
        db.commit()
        db.refresh(run)
        gate = ApprovalGate(
            run_id=run.id,
            gate="patch_review",
            status="pending",
            device_id=bound_id,
        )
        notify_devices_of_approval_gate(db, run, gate)
    finally:
        db.close()
    assert sent == ["bound-fcm"]


def test_expiry_recreation_preserves_bound_device():
    device_id = _id("expire-bind")
    _insert_device(device_id, new_secret())
    db = SessionLocal()
    try:
        run = SandboxRun(
            status="queued",
            repo="a/b",
            ref="main",
            control_state="active",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        gate = ApprovalGate(
            run_id=run.id,
            gate="sandbox_provision",
            status="pending",
            device_id=device_id,
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=5),
        )
        db.add(gate)
        db.commit()
        apply_gate_expiry(db, gate, recreate=True, notify=False)
        pending = (
            db.query(ApprovalGate)
            .filter(
                ApprovalGate.run_id == run.id,
                ApprovalGate.status == "pending",
            )
            .all()
        )
        assert len(pending) == 1
        assert pending[0].device_id == device_id
        assert pending[0].id != gate.id
    finally:
        db.close()


def test_unassigned_pending_gate_is_not_claimable():
    device_id = _id("null-claim")
    secret = new_secret()
    _insert_device(device_id, secret)
    run_id, gate_id = _insert_run_and_gate(None)
    response = client.post(
        f"/v1/sandbox/runs/{run_id}/approval",
        headers=API_HEADERS,
        json={"device_id": device_id, "otp_code": pyotp.TOTP(secret).now()},
    )
    assert response.status_code == 403
    stored = _gate(gate_id)
    assert stored.status == "pending"
    assert stored.device_id is None


def test_try_claim_rejects_unbound_device_while_still_pending():
    device_a = _id("race-a")
    gate = ApprovalGate(
        id=9001,
        run_id=1,
        gate="sandbox_provision",
        status="pending",
        device_id=device_a,
    )

    class Query:
        def filter(self, *args, **kwargs):
            return self

        def with_for_update(self, *args, **kwargs):
            return self

        def one_or_none(self):
            if gate.status != "pending":
                return None
            return gate

    class DB:
        def query(self, model):
            return Query()

    try:
        try_claim_pending_gate(DB(), 9001, _id("race-b"))
        raise AssertionError("unbound device must not claim a pending gate")
    except HTTPException as exc:
        assert exc.status_code == 403
    assert gate.status == "pending"
    assert gate.device_id == device_a
    claimed = try_claim_pending_gate(DB(), 9001, device_a)
    assert claimed is gate
    assert gate.status == "approved"
    assert try_claim_pending_gate(DB(), 9001, device_a) is None


def test_revoked_bound_device_still_forbidden():
    device_id = _id("revoked-bound")
    secret = new_secret()
    _insert_device(device_id, secret, revoked=True)
    run_id, gate_id = _insert_run_and_gate(device_id)
    response = client.post(
        f"/v1/sandbox/runs/{run_id}/approval",
        headers=API_HEADERS,
        json={"device_id": device_id, "otp_code": pyotp.TOTP(secret).now()},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "device revoked"
    assert _gate(gate_id).status == "pending"
