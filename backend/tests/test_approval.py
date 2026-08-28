from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models import ApprovalGate, Device, SandboxRun
from app.services.totp import new_secret
import pyotp

client = TestClient(app)


class FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def one_or_none(self):
        return self._result

    def first(self):
        return self._result

    def all(self):
        if self._result is None:
            return []
        return [self._result]


class FakeDB:
    def __init__(self, run, gate, device):
        self.run = run
        self.gate = gate
        self.device = device

    def query(self, model):
        if model is SandboxRun:
            return FakeQuery(self.run)
        if model is ApprovalGate:
            return FakeQuery(self.gate)
        if model is Device:
            return FakeQuery(self.device)
        return FakeQuery(None)

    def add(self, obj):
        return None

    def commit(self):
        return None

    def refresh(self, obj):
        return None


def test_approval_rejects_unknown_device():
    run = SandboxRun(id=1, status="queued", repo="a/b", ref="main")
    gate = ApprovalGate(
        id=1,
        run_id=1,
        gate="sandbox_provision",
        status="pending",
    )
    db = FakeDB(run, gate, None)
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = client.post(
            "/v1/sandbox/runs/1/approval",
            headers={"X-API-Key": "dev-local-key"},
            json={"device_id": "unknown", "otp_code": "123456"},
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_approval_rejects_invalid_otp():
    secret = new_secret()
    run = SandboxRun(id=1, status="queued", repo="a/b", ref="main")
    gate = ApprovalGate(
        id=1,
        run_id=1,
        gate="sandbox_provision",
        status="pending",
    )
    device = Device(
        device_id="dev-1",
        fcm_token="x",
        totp_secret=secret,
    )
    db = FakeDB(run, gate, device)
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = client.post(
            "/v1/sandbox/runs/1/approval",
            headers={"X-API-Key": "dev-local-key"},
            json={"device_id": "dev-1", "otp_code": "000000"},
        )
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_approval_accepts_valid_totp(monkeypatch):
    secret = new_secret()
    run = SandboxRun(id=1, status="queued", repo="a/b", ref="main")
    gate = ApprovalGate(
        id=1,
        run_id=1,
        gate="sandbox_provision",
        status="pending",
    )
    device = Device(
        device_id="dev-1",
        fcm_token="x",
        totp_secret=secret,
    )
    db = FakeDB(run, gate, device)
    app.dependency_overrides[get_db] = lambda: db
    delayed = []

    class Result:
        id = "approval-task"

    monkeypatch.setattr(
        "app.routers.sandbox.clone_and_index.delay",
        lambda run_id: delayed.append(run_id) or Result(),
    )
    try:
        code = pyotp.TOTP(secret).now()
        response = client.post(
            "/v1/sandbox/runs/1/approval",
            headers={"X-API-Key": "dev-local-key"},
            json={"device_id": "dev-1", "otp_code": code},
        )
        assert response.status_code == 200
        assert delayed == [1]
        assert gate.status == "approved"
    finally:
        app.dependency_overrides.clear()
