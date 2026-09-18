from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_db
from app.main import app
from app.models import ApprovalGate, Device, DeviceAuthReplay, Repository, SandboxRun
from app.services.approval import (
    GATE_TTL_SECONDS,
    SANDBOX_PROVISION_GATE,
    expire_stale_gates,
    try_claim_pending_gate,
)
from app.services.totp import new_secret
from app.workers.tasks import _require_gate_or_retry
import pyotp

client = TestClient(app)


def _clause_requires_pending(arg) -> bool:
    right = getattr(arg, "right", None)
    left = getattr(arg, "left", None)
    if getattr(right, "value", None) == "pending":
        return True
    if getattr(left, "value", None) == "pending":
        return True
    return "pending" in str(arg)


class Query:
    def __init__(self, result):
        self._result = result
        self._pending_only = False

    def filter(self, *args, **kwargs):
        for arg in args:
            if _clause_requires_pending(arg):
                self._pending_only = True
        return self

    def order_by(self, *args, **kwargs):
        return self

    def join(self, *args, **kwargs):
        return self

    def limit(self, n):
        return self

    def with_for_update(self, *args, **kwargs):
        return self

    def all(self):
        row = self.one_or_none()
        if row is None:
            return []
        if isinstance(row, list):
            return row
        return [row]

    def one_or_none(self):
        if self._result is None:
            return None
        if isinstance(self._result, list):
            row = self._result[0] if self._result else None
        else:
            row = self._result
        if self._pending_only:
            status = (
                getattr(row[0], "status", None)
                if isinstance(row, tuple)
                else getattr(row, "status", None)
            )
            if status != "pending":
                return None
        return row

    def first(self):
        return self.one_or_none()

    def one(self):
        result = self.one_or_none()
        if result is None:
            raise LookupError("no row")
        return result


def _clause_eq(arg):
    left = getattr(arg, "left", None)
    right = getattr(arg, "right", None)
    name = getattr(left, "key", None)
    val = getattr(right, "value", None)
    if val is None:
        val = getattr(right, "effective_value", None)
    return name, val


class ReplayQuery:
    def __init__(self, rows):
        self._rows = rows
        self._eq = {}

    def filter(self, *args, **kwargs):
        for arg in args:
            name, val = _clause_eq(arg)
            if name is not None:
                self._eq[name] = val
        return self

    def with_for_update(self, *args, **kwargs):
        return self

    def one_or_none(self):
        for row in self._rows:
            if self._eq.get("device_id", row.device_id) != row.device_id:
                continue
            if self._eq.get("action_key", row.action_key) != row.action_key:
                continue
            if (
                self._eq.get("credential_hash", row.credential_hash)
                != row.credential_hash
            ):
                continue
            return row
        return None


class LifecycleDB:
    def __init__(self, repo, run, gate, device):
        self.repo = repo
        self.run = run
        self.gate = gate
        self.device = device
        self.added = []
        self.replays = []

    def query(self, *models):
        if models and models[0] is Repository:
            return Query(self.repo)
        if len(models) == 2 and models[0] is ApprovalGate:
            return Query([(self.gate, self.run)] if self.gate else [])
        if models and models[0] is SandboxRun:
            return Query(self.run)
        if models and models[0] is ApprovalGate:
            return Query(self.gate)
        if models and models[0] is Device:
            return Query(self.device)
        if models and models[0] is DeviceAuthReplay:
            return ReplayQuery(self.replays)
        return Query(None)

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, DeviceAuthReplay):
            self.replays.append(obj)
        if isinstance(obj, SandboxRun) and obj.id is None:
            obj.id = 421
        if isinstance(obj, ApprovalGate) and obj.id is None:
            obj.id = 1
            self.gate = obj

    def flush(self):
        return None

    def delete(self, obj):
        if obj in self.replays:
            self.replays.remove(obj)
        return None

    def commit(self):
        return None

    def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = 421


def test_create_run_returns_pending_provision_and_enqueues(monkeypatch):
    delayed = []

    class Result:
        id = "clone-task"

    repo = Repository(
        full_name="mahnoor-sardar/AutoPatch-Engine",
        installation_id=1,
        default_branch="main",
    )
    device = Device(device_id="dev-1", fcm_token="x", totp_secret=new_secret())
    db = LifecycleDB(repo, None, None, device)
    monkeypatch.setattr(settings, "approval_device_id", "dev-1")
    monkeypatch.setattr(
        "app.routers.sandbox.clone_and_index.delay",
        lambda run_id: delayed.append(("clone", run_id)) or Result(),
    )
    monkeypatch.setattr("app.services.fcm.send_push", lambda *a, **k: "ok")
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = client.post(
            "/v1/sandbox/runs",
            headers={"X-API-Key": "dev-local-key"},
            json={"repo": "mahnoor-sardar/AutoPatch-Engine", "ref": "main"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "queued"
        assert body["pipeline_stage"] == "provision"
        assert body["approval_gate"] == SANDBOX_PROVISION_GATE
        assert body["approval_status"] == "pending"
        assert delayed == [("clone", 421)]
        assert db.gate is not None
        assert db.gate.status == "pending"
        assert db.gate.device_id == "dev-1"
    finally:
        app.dependency_overrides.clear()


def test_approve_marks_gate_approved_and_enqueues(monkeypatch):
    delayed = []
    secret = new_secret()
    run = SandboxRun(id=421, status="queued", repo="a/b", ref="main")
    gate = ApprovalGate(
        id=1,
        run_id=421,
        gate=SANDBOX_PROVISION_GATE,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=GATE_TTL_SECONDS),
        device_id="dev-1",
    )
    device = Device(device_id="dev-1", fcm_token="x", totp_secret=secret)
    db = LifecycleDB(None, run, gate, device)
    monkeypatch.setattr(
        "app.routers.sandbox.clone_and_index.delay",
        lambda run_id: delayed.append(run_id) or type("R", (), {"id": "t"})(),
    )
    app.dependency_overrides[get_db] = lambda: db
    try:
        code = pyotp.TOTP(secret).now()
        response = client.post(
            "/v1/sandbox/runs/421/approval",
            headers={"X-API-Key": "dev-local-key"},
            json={"device_id": "dev-1", "otp_code": code},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "approved"
        assert gate.status == "approved"
        assert delayed == [421]
        assert gate.status == "approved"
    finally:
        app.dependency_overrides.clear()


def test_replay_of_approved_gate_does_not_enqueue_again(monkeypatch):
    delayed = []
    secret = new_secret()
    run = SandboxRun(id=421, status="queued", repo="a/b", ref="main")
    gate = ApprovalGate(
        id=1,
        run_id=421,
        gate=SANDBOX_PROVISION_GATE,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=GATE_TTL_SECONDS),
        device_id="dev-1",
    )
    device = Device(device_id="dev-1", fcm_token="x", totp_secret=secret)
    db = LifecycleDB(None, run, gate, device)
    monkeypatch.setattr(
        "app.routers.sandbox.clone_and_index.delay",
        lambda run_id: delayed.append(run_id) or type("R", (), {"id": "t"})(),
    )
    app.dependency_overrides[get_db] = lambda: db
    try:
        code = pyotp.TOTP(secret).now()
        first = client.post(
            "/v1/sandbox/runs/421/approval",
            headers={"X-API-Key": "dev-local-key"},
            json={"device_id": "dev-1", "otp_code": code},
        )
        assert first.status_code == 200
        assert delayed == [421]
        replay = client.post(
            "/v1/sandbox/runs/421/approval",
            headers={"X-API-Key": "dev-local-key"},
            json={"device_id": "dev-1", "otp_code": code},
        )
        assert replay.status_code == 200
        assert replay.json()["status"] == "approved"
        assert delayed == [421]
    finally:
        app.dependency_overrides.clear()


def test_try_claim_pending_gate_only_succeeds_once():
    gate = ApprovalGate(
        id=7,
        run_id=1,
        gate=SANDBOX_PROVISION_GATE,
        status="pending",
        device_id="dev-1",
    )

    class ClaimDB:
        def query(self, model):
            return Query(gate)

    try:
        try_claim_pending_gate(ClaimDB(), 7, "dev-2")
        raise AssertionError("unbound device must not claim")
    except HTTPException as exc:
        assert exc.status_code == 403
    assert gate.status == "pending"
    assert gate.device_id == "dev-1"

    first = try_claim_pending_gate(ClaimDB(), 7, "dev-1")
    assert first is gate
    assert gate.status == "approved"
    assert gate.device_id == "dev-1"
    assert gate.approved_at is not None
    second = try_claim_pending_gate(ClaimDB(), 7, "dev-1")
    assert second is None
    assert gate.device_id == "dev-1"


def test_worker_still_accepts_approved_gate_after_claim():
    class Task:
        class request:
            called_directly = True

    run = SandboxRun(id=1, status="queued", repo="a/b", ref="main")
    gate = ApprovalGate(
        run_id=1,
        gate="sandbox_provision",
        status="approved",
    )

    class DB:
        def query(self, model):
            return Query(gate if model is ApprovalGate else run)

        def refresh(self, obj):
            return None

    claimed = _require_gate_or_retry(Task(), DB(), run, "sandbox_provision")
    assert claimed is gate
    assert claimed.status == "approved"


def test_reject_stops_run_and_hides_pending(monkeypatch):
    delayed = []
    secret = new_secret()
    run = SandboxRun(id=421, status="queued", repo="a/b", ref="main")
    gate = ApprovalGate(
        id=1,
        run_id=421,
        gate=SANDBOX_PROVISION_GATE,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=GATE_TTL_SECONDS),
        device_id="dev-1",
    )
    device = Device(device_id="dev-1", fcm_token="x", totp_secret=secret)
    db = LifecycleDB(None, run, gate, device)
    monkeypatch.setattr(
        "app.routers.sandbox.clone_and_index.delay",
        lambda run_id: delayed.append(run_id),
    )
    app.dependency_overrides[get_db] = lambda: db
    try:
        code = pyotp.TOTP(secret).now()
        response = client.post(
            "/v1/sandbox/runs/421/rejection",
            headers={"X-API-Key": "dev-local-key"},
            json={"device_id": "dev-1", "otp_code": code},
        )
        assert response.status_code == 200
        assert run.status == "rejected"
        assert gate.status == "rejected"
        assert delayed == []
        assert run.status == "rejected"
        assert gate.status == "rejected"
    finally:
        app.dependency_overrides.clear()


def test_worker_does_not_fail_rejected_or_expired_gate():
    class Task:
        class request:
            called_directly = True

    run = SandboxRun(id=1, status="rejected", repo="a/b", ref="main")
    gate = ApprovalGate(
        run_id=1,
        gate="sandbox_provision",
        status="rejected",
    )

    class DB:
        def query(self, model):
            return Query(gate if model is ApprovalGate else run)

        def refresh(self, obj):
            return None

    assert _require_gate_or_retry(Task(), DB(), run, "sandbox_provision") is None


def test_pending_list_excludes_expired_without_recreate(monkeypatch):
    monkeypatch.setattr("app.services.fcm.send_push_with_timeout", lambda *a, **k: "ok")
    run = SandboxRun(
        id=421,
        status="queued",
        repo="a/b",
        ref="main",
        control_state="active",
    )
    gate = ApprovalGate(
        id=9,
        run_id=421,
        gate=SANDBOX_PROVISION_GATE,
        status="pending",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db = LifecycleDB(None, run, gate, None)
    expired = expire_stale_gates(db, notify=False, recreate=False)
    assert expired
    assert gate.status == "expired"
    assert run.status == "paused"
    pending = [
        g for g in [db.gate] if g.status == "pending"
    ]
    assert pending == []


def test_clone_claim_queued_not_later_stage():
    from datetime import datetime, timezone

    from app.services.approval import STAGE_CLONE
    from app.workers.tasks import _claim_clone_stage

    queued = SandboxRun(id=1, status="queued", pipeline_stage="provision")
    completed = SandboxRun(
        id=2,
        status="completed",
        pipeline_stage=STAGE_CLONE,
        finished_at=datetime.now(timezone.utc),
        duration_ms=10,
    )

    class DBQueued:
        def query(self, model):
            return Query(queued)

        def commit(self):
            return None

    class DBCompleted:
        def query(self, model):
            return Query(completed)

        def commit(self):
            return None

    started = datetime.now(timezone.utc)
    assert _claim_clone_stage(DBQueued(), queued, started) is True
    assert queued.status == "running"
    assert queued.finished_at is None
    assert _claim_clone_stage(DBCompleted(), completed, started) is False
    assert completed.status == "completed"
