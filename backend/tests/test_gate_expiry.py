from datetime import datetime, timedelta, timezone

from app.models import ApprovalGate, Device, PushEvent, SandboxRun
from app.services.approval import (
    STAGE_CLONE,
    STAGE_PROVISION,
    apply_gate_expiry,
    expire_stale_gates,
    gate_is_expired,
)
from app.routers.sandbox import resume_paused_run


class Query:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        if self._result is None:
            return []
        if isinstance(self._result, list):
            return self._result
        return [self._result]

    def one_or_none(self):
        if isinstance(self._result, list):
            return self._result[0] if self._result else None
        return self._result

    def first(self):
        return self.one_or_none()


class RecordingDB:
    def __init__(self, run, gates, devices=None):
        self.run = run
        self.gates = gates
        self.devices = devices or []
        self.added = []

    def query(self, model):
        if model is ApprovalGate:
            return Query(self.gates)
        if model is SandboxRun:
            return Query(self.run)
        if model is Device:
            return Query(self.devices)
        if model is PushEvent:
            return Query([])
        return Query(None)

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, ApprovalGate):
            obj.id = len(self.gates) + 1
            self.gates = list(self.gates) + [obj] if isinstance(self.gates, list) else [self.gates, obj]

    def commit(self):
        return None

    def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = 99


def test_gate_is_expired_when_ttl_elapsed():
    gate = ApprovalGate(
        run_id=1,
        gate="sandbox_provision",
        status="pending",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    assert gate_is_expired(gate) is True


def test_apply_gate_expiry_pauses_run_and_recreates_gate(monkeypatch):
    run = SandboxRun(
        id=1,
        status="queued",
        repo="a/b",
        ref="main",
        control_state="active",
        pipeline_stage=STAGE_PROVISION,
    )
    gate = ApprovalGate(
        id=1,
        run_id=1,
        gate="sandbox_provision",
        status="pending",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=5),
    )
    db = RecordingDB(run, [gate])
    monkeypatch.setattr("app.services.fcm.send_push", lambda *a, **k: "ok")
    apply_gate_expiry(db, gate, recreate=True)
    assert gate.status == "expired"
    assert run.control_state == "paused"
    assert run.status == "paused"
    actions = [item.action for item in db.added if hasattr(item, "action")]
    assert "expire" in actions
    pending = [g for g in db.gates if isinstance(g, ApprovalGate) and g.status == "pending"]
    assert pending


def test_expire_stale_gates_skips_fresh_gates(monkeypatch):
    run = SandboxRun(id=1, status="queued", repo="a/b", ref="main")
    fresh = ApprovalGate(
        id=1,
        run_id=1,
        gate="sandbox_provision",
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
    )
    db = RecordingDB(run, [fresh])
    monkeypatch.setattr("app.services.fcm.send_push", lambda *a, **k: "ok")
    assert expire_stale_gates(db) == []
    assert fresh.status == "pending"


def test_expire_stale_gates_without_notify_still_recreates(monkeypatch):
    pushes = []
    monkeypatch.setattr(
        "app.services.fcm.send_push",
        lambda *a, **k: pushes.append(1) or "ok",
    )
    monkeypatch.setattr(
        "app.services.fcm.send_push_with_timeout",
        lambda *a, **k: pushes.append(1) or "ok",
    )
    run = SandboxRun(
        id=1,
        status="queued",
        repo="a/b",
        ref="main",
        control_state="active",
        pipeline_stage=STAGE_PROVISION,
    )
    gate = ApprovalGate(
        id=1,
        run_id=1,
        gate="sandbox_provision",
        status="pending",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=5),
    )
    db = RecordingDB(run, [gate])
    expired = expire_stale_gates(db, notify=False)
    assert expired
    assert gate.status == "expired"
    pending = [g for g in db.gates if isinstance(g, ApprovalGate) and g.status == "pending"]
    assert pending
    assert pushes == []


def test_resume_clone_stage_enqueues_clone(monkeypatch):
    delayed = []
    monkeypatch.setattr(
        "app.routers.sandbox.clone_and_index.delay",
        lambda run_id: delayed.append(run_id),
    )
    run = SandboxRun(
        id=7,
        status="paused",
        repo="a/b",
        ref="main",
        control_state="paused",
        pipeline_stage=STAGE_CLONE,
    )
    db = RecordingDB(run, [])
    resume_paused_run(run, db)
    assert delayed == [7]
    assert run.control_state == "active"


def test_resume_provision_without_approval_does_not_clone(monkeypatch):
    delayed = []
    monkeypatch.setattr(
        "app.routers.sandbox.clone_and_index.delay",
        lambda run_id: delayed.append(run_id),
    )
    monkeypatch.setattr("app.services.fcm.send_push", lambda *a, **k: "ok")
    run = SandboxRun(
        id=8,
        status="paused",
        repo="a/b",
        ref="main",
        control_state="paused",
        pipeline_stage=STAGE_PROVISION,
    )
    gate = ApprovalGate(
        id=1,
        run_id=8,
        gate="sandbox_provision",
        status="pending",
    )
    db = RecordingDB(run, [gate])
    resume_paused_run(run, db)
    assert delayed == []
    assert run.control_state == "active"


def test_kill_invokes_provider(monkeypatch):
    from fastapi.testclient import TestClient
    import pyotp

    from app.db import get_db
    from app.main import app
    from app.models import Device
    from app.services.totp import new_secret

    killed = []

    class Provider:
        def create(self):
            raise NotImplementedError

        def kill(self, sandbox_id):
            killed.append(sandbox_id)

    monkeypatch.setattr(
        "app.routers.sandbox.get_sandbox_provider",
        lambda: Provider(),
    )
    secret = new_secret()
    run = SandboxRun(
        id=1,
        status="running",
        repo="a/b",
        ref="main",
        e2b_sandbox_id="sbx-live",
        control_state="active",
    )
    device = Device(device_id="dev-1", fcm_token="x", totp_secret=secret)

    class DB:
        def query(self, model):
            if model is SandboxRun:
                return Query(run)
            if model is Device:
                return Query(device)
            return Query(None)

        def add(self, obj):
            return None

        def commit(self):
            return None

    app.dependency_overrides[get_db] = lambda: DB()
    client = TestClient(app)
    try:
        code = pyotp.TOTP(secret).now()
        response = client.post(
            "/v1/sandbox/runs/1/kill",
            headers={"X-API-Key": "dev-local-key"},
            json={"device_id": "dev-1", "otp_code": code},
        )
        assert response.status_code == 200
        assert killed == ["sbx-live"]
        assert run.status == "killed"
    finally:
        app.dependency_overrides.clear()
