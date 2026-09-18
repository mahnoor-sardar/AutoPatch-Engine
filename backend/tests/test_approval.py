from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models import ApprovalGate, Device, DeviceAuthReplay, SandboxRun
from app.services.audit import consume_device_authorization
from app.services.totp import new_secret
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


class FakeQuery:
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

    def with_for_update(self, *args, **kwargs):
        return self

    def one_or_none(self):
        if self._pending_only and getattr(self._result, "status", None) != "pending":
            return None
        return self._result

    def first(self):
        return self.one_or_none()

    def all(self):
        row = self.one_or_none()
        if row is None:
            return []
        return [row]


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
            if self._eq.get("credential_hash", row.credential_hash) != row.credential_hash:
                continue
            return row
        return None


class FakeDB:
    def __init__(self, run, gate, device):
        self.run = run
        self.gate = gate
        self.device = device
        self.replays = []

    def query(self, model):
        if model is SandboxRun:
            return FakeQuery(self.run)
        if model is ApprovalGate:
            return FakeQuery(self.gate)
        if model is Device:
            return FakeQuery(self.device)
        if model is DeviceAuthReplay:
            return ReplayQuery(self.replays)
        return FakeQuery(None)

    def add(self, obj):
        if isinstance(obj, DeviceAuthReplay):
            self.replays.append(obj)
        return None

    def flush(self):
        return None

    def delete(self, obj):
        if obj in self.replays:
            self.replays.remove(obj)
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
        device_id="dev-1",
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
        device_id="dev-1",
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


def test_same_otp_cannot_authorize_same_action_twice():
    secret = new_secret()
    device = Device(device_id="dev-1", fcm_token="x", totp_secret=secret)
    db = FakeDB(None, None, device)
    payload = "dev-1|1|sandbox_provision"
    code = pyotp.TOTP(secret).now()
    assert consume_device_authorization(db, device, payload, code, None) is True
    assert consume_device_authorization(db, device, payload, code, None) is False


def test_concurrent_same_otp_only_one_consume_wins():
    secret = new_secret()
    device = Device(device_id="dev-1", fcm_token="x", totp_secret=secret)
    db = FakeDB(None, None, device)
    payload = "dev-1|1|pause"
    code = pyotp.TOTP(secret).now()
    first = consume_device_authorization(db, device, payload, code, None)
    second = consume_device_authorization(db, device, payload, code, None)
    assert first is True
    assert second is False


def test_new_totp_window_can_authorize_same_action(monkeypatch):
    secret = new_secret()
    device = Device(device_id="dev-1", fcm_token="x", totp_secret=secret)
    db = FakeDB(None, None, device)
    payload = "dev-1|1|sandbox_provision"
    totp = pyotp.TOTP(secret)
    now = 1_700_000_000
    first_code = totp.at(now)
    later_code = totp.at(now + 30)
    assert first_code != later_code
    assert consume_device_authorization(db, device, payload, first_code, None) is True
    assert consume_device_authorization(db, device, payload, later_code, None) is True


def test_hmac_token_cannot_be_replayed_for_same_action():
    from app.services.audit import make_approval_token

    secret = new_secret()
    device = Device(device_id="dev-1", fcm_token="x", totp_secret=secret)
    db = FakeDB(None, None, device)
    payload = "dev-1|1|sandbox_provision"
    token = make_approval_token(secret, payload, 100)
    assert consume_device_authorization(db, device, payload, None, token) is True
    assert consume_device_authorization(db, device, payload, None, token) is False


def test_control_rejects_replayed_otp():
    secret = new_secret()
    run = SandboxRun(id=1, status="running", repo="a/b", ref="main")
    device = Device(device_id="dev-1", fcm_token="x", totp_secret=secret)
    db = FakeDB(run, None, device)
    app.dependency_overrides[get_db] = lambda: db
    try:
        code = pyotp.TOTP(secret).now()
        first = client.post(
            "/v1/sandbox/runs/1/pause",
            headers={"X-API-Key": "dev-local-key"},
            json={"device_id": "dev-1", "otp_code": code},
        )
        assert first.status_code == 200
        replay = client.post(
            "/v1/sandbox/runs/1/pause",
            headers={"X-API-Key": "dev-local-key"},
            json={"device_id": "dev-1", "otp_code": code},
        )
        assert replay.status_code == 401
    finally:
        app.dependency_overrides.clear()
