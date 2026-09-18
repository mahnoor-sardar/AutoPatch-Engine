import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models import ApprovalGate, GitHubInstallation, Repository, SandboxRun
from app.services.github_app import verify_webhook_signature

client = TestClient(app)


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


def _signed_headers(body: bytes, event: str) -> dict[str, str]:
    digest = hmac.new(
        settings.github_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-Hub-Signature-256": f"sha256={digest}",
        "X-GitHub-Event": event,
    }


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


def test_push_creates_pending_gate_and_enqueues_clone_once(monkeypatch):
    delayed = []
    monkeypatch.setattr(
        "app.routers.github._enqueue_clone_and_index",
        lambda run_id: delayed.append(run_id),
    )
    monkeypatch.setattr(
        "app.services.fcm.send_push",
        lambda *args, **kwargs: "ok",
    )

    db = SessionLocal()
    try:
        _ensure_owner_repo(db)
    finally:
        db.close()

    body = json.dumps(
        {
            "ref": "refs/heads/main",
            "repository": {"full_name": "owner/repo"},
        }
    ).encode()
    response = client.post(
        "/v1/github/webhook",
        content=body,
        headers=_signed_headers(body, "push"),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("run_id")
    assert payload["gate"] == "sandbox_provision"
    assert payload["gate_status"] == "pending"

    run_id = payload["run_id"]
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.repo == "owner/repo"
        gate = (
            db.query(ApprovalGate)
            .filter(
                ApprovalGate.run_id == run_id,
                ApprovalGate.gate == "sandbox_provision",
            )
            .order_by(ApprovalGate.id.desc())
            .first()
        )
        assert gate is not None
        assert gate.status == "pending"
    finally:
        db.close()

    assert delayed == [run_id]


def test_push_stores_valid_after_sha_and_keeps_ref(monkeypatch):
    delayed = []
    monkeypatch.setattr(
        "app.routers.github._enqueue_clone_and_index",
        lambda run_id: delayed.append(run_id),
    )
    monkeypatch.setattr("app.services.fcm.send_push", lambda *args, **kwargs: "ok")
    db = SessionLocal()
    try:
        _ensure_owner_repo(db)
    finally:
        db.close()
    sha = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    body = json.dumps(
        {
            "ref": "refs/heads/main",
            "after": sha,
            "repository": {"full_name": "owner/repo"},
        }
    ).encode()
    response = client.post(
        "/v1/github/webhook",
        content=body,
        headers=_signed_headers(body, "push"),
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.ref == "main"
        assert run.source_sha == sha
    finally:
        db.close()
    assert delayed == [run_id]


def test_push_ignores_invalid_and_zero_after(monkeypatch):
    monkeypatch.setattr(
        "app.routers.github._enqueue_clone_and_index",
        lambda run_id: None,
    )
    monkeypatch.setattr("app.services.fcm.send_push", lambda *args, **kwargs: "ok")
    db = SessionLocal()
    try:
        _ensure_owner_repo(db)
    finally:
        db.close()
    for after in ("main", "0" * 40, "deadbeef"):
        body = json.dumps(
            {
                "ref": "refs/heads/main",
                "after": after,
                "repository": {"full_name": "owner/repo"},
            }
        ).encode()
        response = client.post(
            "/v1/github/webhook",
            content=body,
            headers=_signed_headers(body, "push"),
        )
        run_id = response.json()["run_id"]
        db = SessionLocal()
        try:
            run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
            assert run.ref == "main"
            assert run.source_sha is None
        finally:
            db.close()


def test_duplicate_push_creates_separate_runs_and_jobs(monkeypatch):
    delayed = []
    monkeypatch.setattr(
        "app.routers.github._enqueue_clone_and_index",
        lambda run_id: delayed.append(run_id),
    )
    monkeypatch.setattr(
        "app.services.fcm.send_push",
        lambda *args, **kwargs: "ok",
    )

    db = SessionLocal()
    try:
        _ensure_owner_repo(db)
    finally:
        db.close()

    body = json.dumps(
        {
            "ref": "refs/heads/main",
            "repository": {"full_name": "owner/repo"},
        }
    ).encode()
    headers = _signed_headers(body, "push")
    first = client.post("/v1/github/webhook", content=body, headers=headers)
    second = client.post("/v1/github/webhook", content=body, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    first_id = first.json()["run_id"]
    second_id = second.json()["run_id"]
    assert first_id != second_id
    assert delayed == [first_id, second_id]
