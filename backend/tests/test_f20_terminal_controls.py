from datetime import datetime, timezone

from fastapi.testclient import TestClient
import pyotp
import pytest

from app.db import SessionLocal
from app.main import app
from app.models import ApprovalGate, AuditEvent, SandboxRun
from app.routers.sandbox import resume_paused_run
from app.services.approval import STAGE_CLONE, STAGE_PATCH_APPLY, STAGE_PR, apply_gate_expiry
from tests.conftest import TEST_APPROVAL_DEVICE_ID, TEST_APPROVAL_TOTP_SECRET
from tests.test_gate_expiry import RecordingDB
from tests.test_worker import _ensure_test_repository

client = TestClient(app)
API_HEADERS = {"X-API-Key": "dev-local-key"}


def _otp():
    return pyotp.TOTP(TEST_APPROVAL_TOTP_SECRET).now()


def _control(run_id, action):
    return client.post(
        f"/v1/sandbox/runs/{run_id}/{action}",
        headers=API_HEADERS,
        json={"device_id": TEST_APPROVAL_DEVICE_ID, "otp_code": _otp()},
    )


def _seed_run(**kwargs):
    db = SessionLocal()
    try:
        repo = _ensure_test_repository(db)
        run = SandboxRun(
            repo=repo.full_name,
            ref=repo.default_branch,
            **kwargs,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id
    finally:
        db.close()


def _load(run_id):
    db = SessionLocal()
    try:
        return db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
    finally:
        db.close()


def _kill_audits(run_id):
    db = SessionLocal()
    try:
        return (
            db.query(AuditEvent)
            .filter(AuditEvent.run_id == run_id, AuditEvent.action == "kill")
            .all()
        )
    finally:
        db.close()


@pytest.mark.parametrize(
    "status,control_state",
    [
        ("completed", "active"),
        ("failed", "active"),
        ("rejected", "active"),
        ("killed", "killed"),
    ],
)
def test_pause_terminal_returns_409(status, control_state):
    finished = datetime.now(timezone.utc)
    run_id = _seed_run(
        status=status,
        control_state=control_state,
        finished_at=finished,
        duration_ms=10,
        pipeline_stage=STAGE_CLONE,
    )
    response = _control(run_id, "pause")
    assert response.status_code == 409
    again = _load(run_id)
    assert again.status == status
    assert again.control_state == control_state
    assert again.finished_at == finished
    assert again.duration_ms == 10


def test_resume_killed_with_paused_control_state_does_not_enqueue(monkeypatch):
    delayed = []
    monkeypatch.setattr(
        "app.routers.sandbox.clone_and_index.delay",
        lambda run_id: delayed.append(("clone", run_id)),
    )
    monkeypatch.setattr(
        "app.routers.sandbox.apply_patch_and_verify.delay",
        lambda run_id: delayed.append(("apply", run_id)),
    )
    monkeypatch.setattr(
        "app.routers.sandbox.open_github_pr.delay",
        lambda run_id: delayed.append(("pr", run_id)),
    )
    run_id = _seed_run(
        status="killed",
        control_state="paused",
        finished_at=datetime.now(timezone.utc),
        pipeline_stage=STAGE_CLONE,
    )
    response = _control(run_id, "resume")
    assert response.status_code == 409
    assert delayed == []
    again = _load(run_id)
    assert again.status == "killed"
    assert again.control_state == "paused"


def test_resume_requires_status_paused(monkeypatch):
    delayed = []
    monkeypatch.setattr(
        "app.routers.sandbox.clone_and_index.delay",
        lambda run_id: delayed.append(run_id),
    )
    run_id = _seed_run(
        status="completed",
        control_state="paused",
        finished_at=datetime.now(timezone.utc),
        pipeline_stage=STAGE_CLONE,
    )
    response = _control(run_id, "resume")
    assert response.status_code == 409
    assert delayed == []
    again = _load(run_id)
    assert again.status == "completed"


def test_kill_with_provider_success_persists_terminal_and_audit(monkeypatch):
    killed = []

    class Provider:
        def create(self):
            raise NotImplementedError

        def kill(self, sandbox_id):
            killed.append(sandbox_id)

    monkeypatch.setattr("app.routers.sandbox.get_sandbox_provider", lambda: Provider())
    started = datetime.now(timezone.utc)
    run_id = _seed_run(
        status="running",
        control_state="active",
        e2b_sandbox_id="sbx-live",
        started_at=started,
        pipeline_stage=STAGE_CLONE,
    )
    response = _control(run_id, "kill")
    assert response.status_code == 200
    assert killed == ["sbx-live"]
    again = _load(run_id)
    assert again.status == "killed"
    assert again.control_state == "killed"
    assert again.finished_at is not None
    assert again.duration_ms is not None
    assert _kill_audits(run_id)


def test_kill_persists_when_provider_raises(monkeypatch):
    attempted = []

    class Provider:
        def create(self):
            raise NotImplementedError

        def kill(self, sandbox_id):
            attempted.append(sandbox_id)
            raise RuntimeError("sandbox gone")

    monkeypatch.setattr("app.routers.sandbox.get_sandbox_provider", lambda: Provider())
    run_id = _seed_run(
        status="running",
        control_state="active",
        e2b_sandbox_id="sbx-missing",
        started_at=datetime.now(timezone.utc),
        pipeline_stage=STAGE_CLONE,
    )
    response = _control(run_id, "kill")
    assert response.status_code == 200
    assert attempted == ["sbx-missing"]
    again = _load(run_id)
    assert again.status == "killed"
    assert again.control_state == "killed"
    assert again.finished_at is not None
    assert _kill_audits(run_id)


def test_kill_without_sandbox_id_still_persists(monkeypatch):
    attempted = []

    class Provider:
        def create(self):
            raise NotImplementedError

        def kill(self, sandbox_id):
            attempted.append(sandbox_id)

    monkeypatch.setattr("app.routers.sandbox.get_sandbox_provider", lambda: Provider())
    run_id = _seed_run(
        status="running",
        control_state="active",
        e2b_sandbox_id=None,
        started_at=datetime.now(timezone.utc),
        pipeline_stage=STAGE_CLONE,
    )
    response = _control(run_id, "kill")
    assert response.status_code == 200
    assert attempted == []
    again = _load(run_id)
    assert again.status == "killed"
    assert again.control_state == "killed"
    assert again.finished_at is not None
    assert _kill_audits(run_id)


def test_resume_genuinely_paused_clone_apply_pr(monkeypatch):
    delayed = []
    monkeypatch.setattr(
        "app.routers.sandbox.clone_and_index.delay",
        lambda run_id: delayed.append(("clone", run_id)),
    )
    monkeypatch.setattr(
        "app.routers.sandbox.apply_patch_and_verify.delay",
        lambda run_id: delayed.append(("apply", run_id)),
    )
    monkeypatch.setattr(
        "app.routers.sandbox.open_github_pr.delay",
        lambda run_id: delayed.append(("pr", run_id)),
    )
    clone_id = _seed_run(
        status="paused",
        control_state="paused",
        pipeline_stage=STAGE_CLONE,
    )
    apply_id = _seed_run(
        status="paused",
        control_state="paused",
        pipeline_stage=STAGE_PATCH_APPLY,
    )
    pr_id = _seed_run(
        status="paused",
        control_state="paused",
        pipeline_stage=STAGE_PR,
    )
    assert _control(clone_id, "resume").status_code == 200
    assert _control(apply_id, "resume").status_code == 200
    assert _control(pr_id, "resume").status_code == 200
    assert ("clone", clone_id) in delayed
    assert ("apply", apply_id) in delayed
    assert ("pr", pr_id) in delayed
    assert _load(clone_id).status == "queued"
    assert _load(apply_id).status == "queued"
    assert _load(pr_id).status == "queued"
    assert _load(clone_id).control_state == "active"


def test_resume_paused_run_helper_still_enqueues(monkeypatch):
    delayed = []
    monkeypatch.setattr(
        "app.routers.sandbox.apply_patch_and_verify.delay",
        lambda run_id: delayed.append(run_id),
    )
    apply_run = SandboxRun(
        id=31,
        status="paused",
        repo="a/b",
        ref="main",
        control_state="paused",
        pipeline_stage=STAGE_PATCH_APPLY,
    )
    resume_paused_run(apply_run, RecordingDB(apply_run, []))
    assert apply_run.status == "queued"
    assert delayed == [31]


def test_gate_expiry_does_not_pause_terminal_completed():
    run = SandboxRun(
        id=40,
        status="completed",
        repo="a/b",
        ref="main",
        control_state="active",
        pipeline_stage=STAGE_CLONE,
        finished_at=datetime.now(timezone.utc),
    )
    gate = ApprovalGate(
        id=1,
        run_id=40,
        gate="sandbox_provision",
        status="pending",
        device_id="dev-1",
    )
    db = RecordingDB(run, [gate])
    apply_gate_expiry(db, gate, recreate=False, notify=False)
    assert run.status == "completed"
    assert run.control_state == "active"
    assert gate.status == "expired"
