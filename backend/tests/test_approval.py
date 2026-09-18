import time

from fastapi.testclient import TestClient
import pyotp

from app.db import get_db
from app.main import app
from app.models import ApprovalGate, Device, DeviceAuthReplay, SandboxRun
from app.services.audit import (
    _auth_fingerprint,
    consume_device_authorization,
    device_auth_factor,
    make_approval_token,
    verify_device_authorization,
)
from app.services.totp import new_secret

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
    assert consume_device_authorization(
        db, device, payload, code, None, auth_factor="otp"
    ) is True
    assert consume_device_authorization(
        db, device, payload, code, None, auth_factor="otp"
    ) is False


def test_concurrent_same_otp_only_one_consume_wins():
    secret = new_secret()
    device = Device(device_id="dev-1", fcm_token="x", totp_secret=secret)
    db = FakeDB(None, None, device)
    payload = "dev-1|1|pause"
    code = pyotp.TOTP(secret).now()
    first = consume_device_authorization(
        db, device, payload, code, None, auth_factor="otp"
    )
    second = consume_device_authorization(
        db, device, payload, code, None, auth_factor="otp"
    )
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
    assert consume_device_authorization(
        db, device, payload, first_code, None, auth_factor="otp"
    ) is True
    assert consume_device_authorization(
        db, device, payload, later_code, None, auth_factor="otp"
    ) is True


def test_hmac_token_cannot_be_replayed_for_same_action():
    secret = new_secret()
    device = Device(device_id="dev-1", fcm_token="x", totp_secret=secret)
    db = FakeDB(None, None, device)
    payload = "dev-1|1|sandbox_provision"
    token = make_approval_token(secret, payload, 100)
    assert consume_device_authorization(
        db, device, payload, None, token, auth_factor="token"
    ) is True
    assert consume_device_authorization(
        db, device, payload, None, token, auth_factor="token"
    ) is False


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


def _unused_otp(secret: str, code: str) -> str:
    totp = pyotp.TOTP(secret)
    assert not totp.verify(code, valid_window=1)
    return code


def test_invalid_otp_valid_token_winning_factor_is_token():
    secret = new_secret()
    device = Device(device_id="dev-1", fcm_token="x", totp_secret=secret)
    db = FakeDB(None, None, device)
    payload = "dev-1|1|sandbox_provision"
    token_ts = int(time.time())
    token = make_approval_token(secret, payload, token_ts)
    bad_otp = _unused_otp(secret, "000000")

    factor = device_auth_factor(device, bad_otp, token, token_ts, payload)
    assert factor == "token"
    assert verify_device_authorization(device, bad_otp, token, token_ts, payload)

    assert consume_device_authorization(
        db, device, payload, bad_otp, token, auth_factor=factor
    ) is True
    assert len(db.replays) == 1
    token_fp = _auth_fingerprint(device, payload, None, token, "token")
    otp_fp = _auth_fingerprint(device, payload, bad_otp, token, "otp")
    assert db.replays[0].credential_hash == token_fp
    assert db.replays[0].credential_hash != otp_fp


def test_same_valid_token_different_invalid_otp_is_token_replay():
    secret = new_secret()
    device = Device(device_id="dev-1", fcm_token="x", totp_secret=secret)
    db = FakeDB(None, None, device)
    payload = "dev-1|1|sandbox_provision"
    token_ts = int(time.time())
    token = make_approval_token(secret, payload, token_ts)
    otp_a = _unused_otp(secret, "000000")
    otp_b = _unused_otp(secret, "111111")
    assert otp_a != otp_b

    factor_a = device_auth_factor(device, otp_a, token, token_ts, payload)
    factor_b = device_auth_factor(device, otp_b, token, token_ts, payload)
    assert factor_a == "token"
    assert factor_b == "token"

    assert consume_device_authorization(
        db, device, payload, otp_a, token, auth_factor=factor_a
    ) is True
    first_hash = db.replays[0].credential_hash
    token_fp = _auth_fingerprint(device, payload, None, token, "token")
    otp_a_fp = _auth_fingerprint(device, payload, otp_a, None, "otp")
    otp_b_fp = _auth_fingerprint(device, payload, otp_b, None, "otp")
    assert first_hash == token_fp
    assert first_hash != otp_a_fp
    assert first_hash != otp_b_fp

    assert consume_device_authorization(
        db, device, payload, otp_b, token, auth_factor=factor_b
    ) is False
    assert len(db.replays) == 1
    assert db.replays[0].credential_hash == first_hash


def test_valid_otp_plus_token_otp_wins_and_token_is_not_consumed():
    secret = new_secret()
    device = Device(device_id="dev-1", fcm_token="x", totp_secret=secret)
    db = FakeDB(None, None, device)
    payload = "dev-1|1|sandbox_provision"
    token_ts = int(time.time())
    token = make_approval_token(secret, payload, token_ts)
    code = pyotp.TOTP(secret).now()

    factor = device_auth_factor(device, code, token, token_ts, payload)
    assert factor == "otp"
    assert consume_device_authorization(
        db, device, payload, code, token, auth_factor=factor
    ) is True
    assert len(db.replays) == 1
    otp_fp = _auth_fingerprint(device, payload, code, None, "otp")
    token_fp = _auth_fingerprint(device, payload, None, token, "token")
    assert db.replays[0].credential_hash == otp_fp
    assert db.replays[0].credential_hash != token_fp
    assert consume_device_authorization(
        db, device, payload, None, token, auth_factor="token"
    ) is True
    assert len(db.replays) == 2


def test_otp_only_remains_one_time():
    secret = new_secret()
    device = Device(device_id="dev-1", fcm_token="x", totp_secret=secret)
    db = FakeDB(None, None, device)
    payload = "dev-1|1|sandbox_provision"
    code = pyotp.TOTP(secret).now()
    assert device_auth_factor(device, code, None, None, payload) == "otp"
    assert consume_device_authorization(
        db, device, payload, code, None, auth_factor="otp"
    ) is True
    assert consume_device_authorization(
        db, device, payload, code, None, auth_factor="otp"
    ) is False


def test_token_only_remains_one_time():
    secret = new_secret()
    device = Device(device_id="dev-1", fcm_token="x", totp_secret=secret)
    db = FakeDB(None, None, device)
    payload = "dev-1|1|sandbox_provision"
    token_ts = int(time.time())
    token = make_approval_token(secret, payload, token_ts)
    assert device_auth_factor(device, None, token, token_ts, payload) == "token"
    assert consume_device_authorization(
        db, device, payload, None, token, auth_factor="token"
    ) is True
    assert consume_device_authorization(
        db, device, payload, None, token, auth_factor="token"
    ) is False


def test_failed_both_does_not_consume_replay():
    secret = new_secret()
    device = Device(device_id="dev-1", fcm_token="x", totp_secret=secret)
    db = FakeDB(None, None, device)
    payload = "dev-1|1|sandbox_provision"
    token_ts = int(time.time())
    bad_otp = _unused_otp(secret, "000000")
    factor = device_auth_factor(
        device, bad_otp, "deadbeef", token_ts, payload
    )
    assert factor is None
    assert not verify_device_authorization(
        device, bad_otp, "deadbeef", token_ts, payload
    )
    assert consume_device_authorization(
        db, device, payload, bad_otp, "deadbeef", auth_factor=factor
    ) is False
    assert db.replays == []


def test_approval_invalid_otp_valid_token_then_token_replay_rejected(monkeypatch):
    secret = new_secret()
    run = SandboxRun(id=1, status="queued", repo="a/b", ref="main")
    gate = ApprovalGate(
        id=1,
        run_id=1,
        gate="sandbox_provision",
        status="pending",
        device_id="dev-1",
    )
    device = Device(device_id="dev-1", fcm_token="x", totp_secret=secret)
    db = FakeDB(run, gate, device)
    app.dependency_overrides[get_db] = lambda: db
    delayed = []

    class Result:
        id = "approval-task"

    monkeypatch.setattr(
        "app.routers.sandbox.clone_and_index.delay",
        lambda run_id: delayed.append(run_id) or Result(),
    )
    payload = "dev-1|1|sandbox_provision"
    token_ts = int(time.time())
    token = make_approval_token(secret, payload, token_ts)
    otp_a = _unused_otp(secret, "000000")
    otp_b = _unused_otp(secret, "111111")
    try:
        first = client.post(
            "/v1/sandbox/runs/1/approval",
            headers={"X-API-Key": "dev-local-key"},
            json={
                "device_id": "dev-1",
                "otp_code": otp_a,
                "approval_token": token,
                "token_ts": token_ts,
            },
        )
        assert first.status_code == 200
        assert len(db.replays) == 1
        token_fp = _auth_fingerprint(device, payload, None, token, "token")
        assert db.replays[0].credential_hash == token_fp
        assert db.replays[0].credential_hash != _auth_fingerprint(
            device, payload, otp_a, None, "otp"
        )

        gate.status = "pending"
        second = client.post(
            "/v1/sandbox/runs/1/approval",
            headers={"X-API-Key": "dev-local-key"},
            json={
                "device_id": "dev-1",
                "otp_code": otp_b,
                "approval_token": token,
                "token_ts": token_ts,
            },
        )
        assert second.status_code == 401
        assert len(db.replays) == 1
        assert db.replays[0].credential_hash == token_fp
    finally:
        app.dependency_overrides.clear()
