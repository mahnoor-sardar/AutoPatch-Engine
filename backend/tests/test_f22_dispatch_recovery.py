from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pyotp

from app.db import SessionLocal
from app.main import app
from app.models import ApprovalGate, SandboxRun
from app.routers.sandbox import resume_paused_run
from app.services.approval import (
    GATE_TTL_SECONDS,
    MERGE_GATE,
    SANDBOX_PROVISION_GATE,
    STAGE_CLONE,
    STAGE_PR,
    STAGE_PROVISION,
)
from app.services.github_pr import create_pull_request, find_open_pull_request
from app.workers.tasks import _claim_pr_stage, open_github_pr
from tests.conftest import TEST_APPROVAL_DEVICE_ID, TEST_APPROVAL_TOTP_SECRET
from tests.test_f09_source_sha import TEST_SOURCE_SHA, _stub_pr_publish
from tests.test_gate_expiry import RecordingDB
from tests.test_patch_pipeline import _approve, _seed_run, _seed_verified_pr_records
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


def _approve_http(run_id):
    return client.post(
        f"/v1/sandbox/runs/{run_id}/approval",
        headers=API_HEADERS,
        json={"device_id": TEST_APPROVAL_DEVICE_ID, "otp_code": _otp()},
    )


def _load(run_id):
    db = SessionLocal()
    try:
        return db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
    finally:
        db.close()


def _load_latest_gate(run_id):
    db = SessionLocal()
    try:
        return (
            db.query(ApprovalGate)
            .filter(ApprovalGate.run_id == run_id)
            .order_by(ApprovalGate.id.desc())
            .first()
        )
    finally:
        db.close()


def _seed_pending_provision_run(**kwargs):
    db = SessionLocal()
    try:
        repo = _ensure_test_repository(db)
        run = SandboxRun(
            status=kwargs.pop("status", "queued"),
            repo=repo.full_name,
            ref=repo.default_branch,
            pipeline_stage=kwargs.pop("pipeline_stage", STAGE_PROVISION),
            **kwargs,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        gate = ApprovalGate(
            run_id=run.id,
            gate=SANDBOX_PROVISION_GATE,
            status="pending",
            device_id=TEST_APPROVAL_DEVICE_ID,
            expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=GATE_TTL_SECONDS),
        )
        db.add(gate)
        db.commit()
        return run.id
    finally:
        db.close()


def test_create_run_commit_survives_delay_failure(monkeypatch):
    delayed = []

    def boom(run_id):
        delayed.append(run_id)
        raise RuntimeError("broker down")

    monkeypatch.setattr("app.routers.sandbox.clone_and_index.delay", boom)
    db = SessionLocal()
    try:
        repo = _ensure_test_repository(db)
        full_name = repo.full_name
    finally:
        db.close()
    response = client.post(
        "/v1/sandbox/runs",
        headers=API_HEADERS,
        json={"repo": full_name, "ref": "main"},
    )
    assert response.status_code == 503
    assert delayed
    run = _load(delayed[0])
    assert run.status == "queued"
    gate = _load_latest_gate(delayed[0])
    assert gate is not None
    assert gate.status == "pending"


def test_approval_commit_survives_delay_failure(monkeypatch):
    def boom(run_id):
        raise RuntimeError("broker down")

    monkeypatch.setattr("app.routers.sandbox.clone_and_index.delay", boom)
    run_id = _seed_pending_provision_run()
    response = _approve_http(run_id)
    assert response.status_code == 503
    gate = _load_latest_gate(run_id)
    assert gate.status == "approved"


def test_already_approved_idle_run_redispatches(monkeypatch):
    delayed = []
    monkeypatch.setattr(
        "app.routers.sandbox.clone_and_index.delay",
        lambda run_id: delayed.append(run_id) or type("R", (), {"id": "t"})(),
    )
    run_id = _seed_pending_provision_run()
    assert _approve_http(run_id).status_code == 200
    assert delayed == [run_id]
    replay = _approve_http(run_id)
    assert replay.status_code == 200
    assert delayed == [run_id, run_id]


def test_already_approved_running_or_terminal_does_not_redispatch(monkeypatch):
    delayed = []
    monkeypatch.setattr(
        "app.routers.sandbox.clone_and_index.delay",
        lambda run_id: delayed.append(run_id) or type("R", (), {"id": "t"})(),
    )
    run_id = _seed_pending_provision_run()
    assert _approve_http(run_id).status_code == 200
    delayed.clear()
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        run.status = "running"
        run.pipeline_stage = STAGE_CLONE
        db.commit()
    finally:
        db.close()
    assert _approve_http(run_id).status_code == 200
    assert delayed == []

    completed_id = _seed_pending_provision_run(
        status="completed",
        pipeline_stage=STAGE_CLONE,
        finished_at=datetime.now(timezone.utc),
    )
    db = SessionLocal()
    try:
        gate = (
            db.query(ApprovalGate)
            .filter(ApprovalGate.run_id == completed_id)
            .one()
        )
        gate.status = "approved"
        db.commit()
    finally:
        db.close()
    delayed.clear()
    assert _approve_http(completed_id).status_code == 200
    assert delayed == []


def test_resume_enqueues_only_after_commit(monkeypatch):
    observed = []

    def delay_after_commit(run_id):
        db = SessionLocal()
        try:
            run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
            observed.append(run.status)
        finally:
            db.close()
        return type("R", (), {"id": "t"})()

    monkeypatch.setattr(
        "app.routers.sandbox.open_github_pr.delay", delay_after_commit
    )
    db = SessionLocal()
    try:
        repo = _ensure_test_repository(db)
        run = SandboxRun(
            status="paused",
            control_state="paused",
            pipeline_stage=STAGE_PR,
            repo=repo.full_name,
            ref=repo.default_branch,
        )
        db.add(run)
        db.commit()
        run_id = run.id
    finally:
        db.close()
    assert _control(run_id, "resume").status_code == 200
    assert observed == ["awaiting_merge"]
    again = _load(run_id)
    assert again.status == "awaiting_merge"
    assert again.control_state == "active"
    assert again.pipeline_stage == STAGE_PR


def test_resume_enqueue_failure_keeps_committed_state(monkeypatch):
    monkeypatch.setattr(
        "app.routers.sandbox.clone_and_index.delay",
        lambda run_id: (_ for _ in ()).throw(RuntimeError("broker down")),
    )
    db = SessionLocal()
    try:
        repo = _ensure_test_repository(db)
        run = SandboxRun(
            status="paused",
            control_state="paused",
            pipeline_stage=STAGE_CLONE,
            repo=repo.full_name,
            ref=repo.default_branch,
        )
        db.add(run)
        db.commit()
        run_id = run.id
    finally:
        db.close()
    response = _control(run_id, "resume")
    assert response.status_code == 503
    again = _load(run_id)
    assert again.status == "queued"
    assert again.control_state == "active"


def test_resume_pr_contract_is_claimable():
    run = SandboxRun(
        id=2201,
        status="paused",
        control_state="paused",
        pipeline_stage=STAGE_PR,
        repo="a/b",
        ref="main",
    )
    task = resume_paused_run(run, RecordingDB(run, []))
    assert run.status == "awaiting_merge"
    assert run.control_state == "active"
    assert run.pipeline_stage == STAGE_PR
    assert task is open_github_pr


def test_claim_pr_stage_still_rejects_queued():
    db = SessionLocal()
    try:
        repo = _ensure_test_repository(db)
        run = SandboxRun(
            status="queued",
            control_state="active",
            pipeline_stage=STAGE_PR,
            repo=repo.full_name,
            ref=repo.default_branch,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        assert _claim_pr_stage(db, run, datetime.now(timezone.utc)) is False
        db.refresh(run)
        assert run.status == "queued"
        assert run.stage_owner_token is None
    finally:
        db.close()


def test_helper_does_not_enqueue_before_caller_commits(monkeypatch):
    delayed = []
    monkeypatch.setattr(
        "app.routers.sandbox.clone_and_index.delay",
        lambda run_id: delayed.append(run_id),
    )
    run = SandboxRun(
        id=9,
        status="paused",
        control_state="paused",
        pipeline_stage=STAGE_CLONE,
        repo="a/b",
        ref="main",
    )
    task = resume_paused_run(run, RecordingDB(run, []))
    assert delayed == []
    from app.workers.tasks import clone_and_index

    assert task is clone_and_index


def test_existing_github_pr_is_persisted_without_create(monkeypatch):
    run_id, _repo = _seed_run(
        status="awaiting_merge",
        current_diff="diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        pipeline_stage="merge",
        source_sha=TEST_SOURCE_SHA,
    )
    _approve(run_id, MERGE_GATE)
    _seed_verified_pr_records(run_id)
    cloned, pushed, prs = _stub_pr_publish(monkeypatch)
    existing = {
        "html_url": "https://github.com/a/b/pull/99",
        "head": {"ref": f"autopatch/run-{run_id}"},
    }
    monkeypatch.setattr(
        "app.workers.tasks.find_open_pull_request",
        lambda *a, **k: existing,
    )
    open_github_pr.run(run_id)
    assert cloned
    assert pushed
    assert prs == []
    run = _load(run_id)
    assert run.pr_url == "https://github.com/a/b/pull/99"
    assert run.status == "completed"


def test_new_pr_creates_exactly_once(monkeypatch):
    run_id, _repo = _seed_run(
        status="awaiting_merge",
        current_diff="diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        pipeline_stage="merge",
        source_sha=TEST_SOURCE_SHA,
    )
    _approve(run_id, MERGE_GATE)
    _seed_verified_pr_records(run_id)
    cloned, pushed, prs = _stub_pr_publish(monkeypatch)
    open_github_pr.run(run_id)
    assert len(prs) == 1
    run = _load(run_id)
    assert run.pr_url.endswith("/pull/1")
    assert run.status == "completed"


def test_create_pull_request_recovers_existing_on_conflict(monkeypatch):
    calls = []

    class ConflictResponse:
        status_code = 422

        def raise_for_status(self):
            raise AssertionError("conflict should be recovered")

        def json(self):
            return {"message": "Validation Failed"}

    class OkList:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "html_url": "https://github.com/a/b/pull/7",
                    "head": {"ref": "autopatch/run-7"},
                }
            ]

    class FakeClient:
        def __init__(self, timeout=30):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            calls.append("post")
            return ConflictResponse()

        def get(self, url, headers=None, params=None):
            calls.append(("get", params))
            return OkList()

    monkeypatch.setattr("app.services.github_pr.httpx.Client", FakeClient)
    result = create_pull_request(
        token="t",
        repo="a/b",
        title="fix",
        body="body",
        head="autopatch/run-7",
        base="main",
    )
    assert result["html_url"].endswith("/pull/7")
    assert "post" in calls
    assert any(item[0] == "get" for item in calls if isinstance(item, tuple))


def test_find_open_pull_request_matches_exact_head(monkeypatch):
    class OkList:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "html_url": "https://github.com/a/b/pull/1",
                    "head": {"ref": "other"},
                },
                {
                    "html_url": "https://github.com/a/b/pull/2",
                    "head": {"ref": "autopatch/run-8"},
                },
            ]

    class FakeClient:
        def __init__(self, timeout=30):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers=None, params=None):
            assert params["head"] == "a:autopatch/run-8"
            assert params["state"] == "open"
            return OkList()

    monkeypatch.setattr("app.services.github_pr.httpx.Client", FakeClient)
    found = find_open_pull_request("t", "a/b", "autopatch/run-8")
    assert found["html_url"].endswith("/pull/2")


def test_pr_retry_after_persist_failure_discovers_existing(monkeypatch):
    run_id, _repo = _seed_run(
        status="awaiting_merge",
        current_diff="diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        pipeline_stage="merge",
        source_sha=TEST_SOURCE_SHA,
    )
    _approve(run_id, MERGE_GATE)
    _seed_verified_pr_records(run_id)
    cloned, pushed, prs = _stub_pr_publish(monkeypatch)
    import app.workers.tasks as tasks

    real_owned = tasks._owned_update

    def fail_pr_url(db, run, owner_token, **fields):
        if "pr_url" in fields:
            return False
        return real_owned(db, run, owner_token, **fields)

    monkeypatch.setattr(tasks, "_owned_update", fail_pr_url)
    open_github_pr.run(run_id)
    assert len(prs) == 1
    run = _load(run_id)
    assert run.pr_url is None
    assert run.status != "completed"
    db = SessionLocal()
    try:
        again = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        again.stage_lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(tasks, "_owned_update", real_owned)
    monkeypatch.setattr(
        "app.workers.tasks.find_open_pull_request",
        lambda *a, **k: {
            "html_url": "https://github.com/a/b/pull/1",
            "head": {"ref": f"autopatch/run-{run_id}"},
        },
    )
    prs.clear()
    open_github_pr.run(run_id)
    assert prs == []
    run = _load(run_id)
    assert run.pr_url == "https://github.com/a/b/pull/1"
    assert run.status == "completed"
