from datetime import datetime, timezone

from app.db import SessionLocal
from app.models import SandboxRun
from app.routers.sandbox import resume_paused_run
from app.services.approval import STAGE_PR
from app.workers.tasks import _claim_pr_stage, open_github_pr
from tests.test_f09_source_sha import TEST_SOURCE_SHA, _stub_pr_publish
from tests.test_gate_expiry import RecordingDB
from tests.test_patch_pipeline import _approve, _seed_run, _seed_verified_pr_records
from tests.test_worker import _ensure_test_repository


def test_paused_pr_resume_produces_claimable_awaiting_merge(monkeypatch):
    delayed = []
    monkeypatch.setattr(
        "app.routers.sandbox.open_github_pr.delay",
        lambda run_id: delayed.append(run_id),
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
            source_sha=TEST_SOURCE_SHA,
            current_diff="diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
        resume_paused_run(run, db)
        db.commit()
        db.refresh(run)
        assert run.status == "awaiting_merge"
        assert run.control_state == "active"
        assert run.pipeline_stage == STAGE_PR
        assert delayed == [run_id]
        started = datetime.now(timezone.utc)
        assert _claim_pr_stage(db, run, started) is True
        db.refresh(run)
        assert run.status == "running"
        assert run.pipeline_stage == STAGE_PR
        assert run.stage_owner_token
        assert run.stage_lease_expires_at is not None
    finally:
        db.close()


def test_paused_pr_resume_queued_is_not_the_claim_state(monkeypatch):
    monkeypatch.setattr(
        "app.routers.sandbox.open_github_pr.delay",
        lambda run_id: None,
    )
    run = SandboxRun(
        id=2101,
        status="paused",
        control_state="paused",
        pipeline_stage=STAGE_PR,
        repo="a/b",
        ref="main",
    )
    resume_paused_run(run, RecordingDB(run, []))
    assert run.status == "awaiting_merge"
    assert run.status != "queued"


def test_resumed_pr_worker_proceeds_past_claim(monkeypatch):
    run_id, _repo = _seed_run(
        status="paused",
        control_state="paused",
        pipeline_stage=STAGE_PR,
        source_sha=TEST_SOURCE_SHA,
        current_diff="diff --git a/x b/x\n--- a/x\n+++ b/x\n",
    )
    _approve(run_id, "merge")
    _seed_verified_pr_records(run_id)
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        resume_paused_run(run, db)
        db.commit()
        assert run.status == "awaiting_merge"
    finally:
        db.close()
    cloned, pushed, prs = _stub_pr_publish(monkeypatch)
    monkeypatch.setattr("app.services.fcm.send_push", lambda *a, **k: "ok")
    open_github_pr.run(run_id)
    assert cloned
    db = SessionLocal()
    try:
        again = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert again.status != "paused"
        assert again.status != "queued"
        assert again.pr_url or again.status in ("completed", "running")
    finally:
        db.close()
    assert pushed
    assert prs
