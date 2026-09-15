import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal, get_db
from app.main import app
from app.models import (
    ApprovalGate,
    ErrorIngest,
    GitHubInstallation,
    Repository,
    SandboxRun,
)

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

LIVE_SENTRY_ERROR_PAYLOAD = {
    "action": "created",
    "data": {
        "error": {
            "exception": {
                "values": [
                    {
                        "type": "ZeroDivisionError",
                        "value": "division by zero",
                        "stacktrace": {
                            "frames": [
                                {
                                    "filename": "test_app.py",
                                    "function": "trigger_error",
                                    "lineno": 10,
                                    "context_line": "division_by_zero = 1 / 0",
                                }
                            ]
                        },
                    }
                ]
            },
            "tags": [
                ["environment", "autopatch-test"],
                ["repo", "owner/repo"],
            ],
        }
    },
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


def test_datadog_rejects_missing_signature(monkeypatch):
    _override_secrets(monkeypatch)
    body = json.dumps(DATADOG_PAYLOAD).encode()
    response = client.post("/v1/webhooks/datadog", content=body)
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


def _ensure_owner_repo(db):
    repo = (
        db.query(Repository)
        .filter(Repository.full_name == "owner/repo")
        .one_or_none()
    )
    if repo is not None:
        return repo
    installation = (
        db.query(GitHubInstallation)
        .filter(GitHubInstallation.installation_id == 1)
        .one_or_none()
    )
    if installation is None:
        db.add(
            GitHubInstallation(
                installation_id=1,
                account_login="owner",
            )
        )
        db.flush()
    repo = Repository(
        full_name="owner/repo",
        installation_id=1,
        default_branch="main",
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return repo


def _payload_with_repo(base: dict) -> dict:
    payload = dict(base)
    payload["repo"] = "owner/repo"
    return payload


def _stub_run_side_effects(monkeypatch) -> list:
    delayed: list[int] = []
    monkeypatch.setattr(
        "app.routers.observability._enqueue_clone_and_index",
        lambda run_id: delayed.append(run_id),
    )
    monkeypatch.setattr(
        "app.services.fcm.send_push",
        lambda *args, **kwargs: "ok",
    )
    return delayed


def _seed_registered_repo() -> tuple[int, int]:
    db = SessionLocal()
    try:
        _ensure_owner_repo(db)
        last_run_id = db.query(SandboxRun.id).order_by(SandboxRun.id.desc()).first()
        last_ingest_id = (
            db.query(ErrorIngest.id).order_by(ErrorIngest.id.desc()).first()
        )
        return (
            last_run_id[0] if last_run_id else 0,
            last_ingest_id[0] if last_ingest_id else 0,
        )
    finally:
        db.close()


def _assert_ingest_created_pending_run(
    *,
    response,
    delayed: list[int],
    last_run_id: int,
    last_ingest_id: int,
    provider: str,
) -> None:
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider"] == provider
    assert payload["id"] > last_ingest_id

    db = SessionLocal()
    try:
        ingest = (
            db.query(ErrorIngest)
            .filter(ErrorIngest.id == payload["id"])
            .one()
        )
        assert ingest.provider == provider
        assert ingest.stack_trace

        run = (
            db.query(SandboxRun)
            .filter(SandboxRun.id > last_run_id)
            .order_by(SandboxRun.id.desc())
            .first()
        )
        assert run is not None
        assert run.status == "queued"
        assert run.repo == "owner/repo"
        assert run.stack_trace

        gate = (
            db.query(ApprovalGate)
            .filter(
                ApprovalGate.run_id == run.id,
                ApprovalGate.gate == "sandbox_provision",
            )
            .order_by(ApprovalGate.id.desc())
            .first()
        )
        assert gate is not None
        assert gate.status == "pending"
        assert delayed == [run.id]
    finally:
        db.close()


def test_sentry_creates_pending_gate_and_enqueues_clone_once(monkeypatch):
    _override_secrets(monkeypatch)
    delayed = _stub_run_side_effects(monkeypatch)
    last_run_id, last_ingest_id = _seed_registered_repo()

    body = json.dumps(_payload_with_repo(SENTRY_PAYLOAD)).encode()
    response = client.post(
        "/v1/webhooks/sentry",
        content=body,
        headers={"Sentry-Hook-Signature": _sign(body, SENTRY_SECRET)},
    )
    _assert_ingest_created_pending_run(
        response=response,
        delayed=delayed,
        last_run_id=last_run_id,
        last_ingest_id=last_ingest_id,
        provider="sentry",
    )


def test_sentry_live_error_payload_creates_pending_gate_and_enqueues_clone_once(
    monkeypatch,
):
    _override_secrets(monkeypatch)
    delayed = _stub_run_side_effects(monkeypatch)
    last_run_id, last_ingest_id = _seed_registered_repo()

    body = json.dumps(LIVE_SENTRY_ERROR_PAYLOAD).encode()
    response = client.post(
        "/v1/webhooks/sentry",
        content=body,
        headers={"Sentry-Hook-Signature": _sign(body, SENTRY_SECRET)},
    )
    _assert_ingest_created_pending_run(
        response=response,
        delayed=delayed,
        last_run_id=last_run_id,
        last_ingest_id=last_ingest_id,
        provider="sentry",
    )
    payload = response.json()
    assert payload["exception_type"] == "ZeroDivisionError"
    assert payload["frames"][0]["file"] == "test_app.py"
    assert payload["frames"][0]["function"] == "trigger_error"
    assert payload["frames"][0]["line"] == 10


def test_datadog_creates_pending_gate_and_enqueues_clone_once(monkeypatch):
    _override_secrets(monkeypatch)
    delayed = _stub_run_side_effects(monkeypatch)
    last_run_id, last_ingest_id = _seed_registered_repo()

    body = json.dumps(_payload_with_repo(DATADOG_PAYLOAD)).encode()
    digest = _sign(body, DATADOG_SECRET)
    response = client.post(
        "/v1/webhooks/datadog",
        content=body,
        headers={"X-Datadog-Signature": f"sha256={digest}"},
    )
    _assert_ingest_created_pending_run(
        response=response,
        delayed=delayed,
        last_run_id=last_run_id,
        last_ingest_id=last_ingest_id,
        provider="datadog",
    )


def test_duplicate_sentry_ingest_creates_separate_runs_and_jobs(monkeypatch):
    _override_secrets(monkeypatch)
    delayed = _stub_run_side_effects(monkeypatch)
    last_run_id, _last_ingest_id = _seed_registered_repo()

    body = json.dumps(_payload_with_repo(SENTRY_PAYLOAD)).encode()
    headers = {"Sentry-Hook-Signature": _sign(body, SENTRY_SECRET)}
    first = client.post("/v1/webhooks/sentry", content=body, headers=headers)
    second = client.post("/v1/webhooks/sentry", content=body, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] != second.json()["id"]
    assert len(delayed) == 2
    assert delayed[0] != delayed[1]
    assert all(run_id > last_run_id for run_id in delayed)
