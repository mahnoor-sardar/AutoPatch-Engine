from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import ReproductionAttempt, SandboxRun
from app.services.approval import STAGE_CLONE, STAGE_PATCH_REVIEW
from app.services.diagnostic import DiagnosticLocation
from app.services.harness import ReproductionResult
from app.workers.tasks import _claim_clone_stage, clone_and_index, open_github_pr, run_state_is_valid
from tests.test_f09_source_sha import _stub_pr_publish
from tests.test_patch_pipeline import (
    SOURCE_FILES,
    TEST_SOURCE_SHA,
    _approve,
    _fake_sandbox,
    _seed_run,
    _stub_repro_pipeline,
)
from tests.test_run_state import LockDB, _now
from tests.test_worker import _ensure_test_repository

client = TestClient(app)
API_HEADERS = {"X-API-Key": "dev-local-key"}


def _stub_clone_only(monkeypatch, files=SOURCE_FILES):
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        lambda **kwargs: (_fake_sandbox(), files),
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.install_project_dependencies",
        lambda sandbox: (0, "", ""),
    )
    monkeypatch.setattr(
        "app.workers.tasks.installation_token_for_repo",
        lambda *args, **kwargs: "test-token",
    )
    monkeypatch.setattr("app.services.fcm.send_push", lambda *a, **k: "ok")

    def must_not_generate_patch(**kwargs):
        raise AssertionError("generate_patch must not be called")

    monkeypatch.setattr("app.workers.tasks.generate_patch", must_not_generate_patch)


def _run_after_clone(run_id):
    db = SessionLocal()
    try:
        return db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
    finally:
        db.close()


def _stats():
    response = client.get("/v1/sandbox/runs", headers=API_HEADERS)
    assert response.status_code == 200
    return response.json()["stats"]


def test_clone_without_stack_trace_fails(monkeypatch):
    run_id, _repo = _seed_run()
    _approve(run_id, "sandbox_provision")
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        run.stack_trace = None
        db.commit()
    finally:
        db.close()
    _stub_clone_only(monkeypatch)
    before = _stats()["successful"]
    clone_and_index.run(run_id)
    run = _run_after_clone(run_id)
    assert run.status == "failed"
    assert run.error == "missing stack_trace"
    assert run.pr_url is None
    assert _stats()["successful"] == before


def test_stack_trace_without_locateable_frames_fails(monkeypatch):
    run_id, _repo = _seed_run()
    _approve(run_id, "sandbox_provision")
    _stub_clone_only(monkeypatch)
    monkeypatch.setattr("app.workers.tasks.locate_frames", lambda *a, **k: [])
    clone_and_index.run(run_id)
    run = _run_after_clone(run_id)
    assert run.status == "failed"
    assert run.error == "no locateable frames"


def test_located_source_missing_fails(monkeypatch):
    run_id, _repo = _seed_run()
    _approve(run_id, "sandbox_provision")
    _stub_clone_only(monkeypatch)
    missing = DiagnosticLocation(
        path="does/not/exist.py",
        name="calculate",
        kind="function",
        start_line=1,
        confidence="high",
    )
    monkeypatch.setattr("app.workers.tasks.locate_frames", lambda *a, **k: [missing])
    clone_and_index.run(run_id)
    run = _run_after_clone(run_id)
    assert run.status == "failed"
    assert run.error == "source file not found"


def test_reproduction_not_reproduced_fails(monkeypatch):
    run_id, _repo = _seed_run()
    _approve(run_id, "sandbox_provision")
    _stub_clone_only(monkeypatch)
    monkeypatch.setattr(
        "app.workers.tasks.run_reproduction_test",
        lambda *a, **k: ReproductionResult(
            exit_code=0,
            stdout="",
            stderr="",
        ),
    )
    clone_and_index.run(run_id)
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        attempt = (
            db.query(ReproductionAttempt)
            .filter(ReproductionAttempt.run_id == run_id)
            .one()
        )
        assert run.status == "failed"
        assert run.error == "bug not reproduced"
        assert attempt.reproduced is False
    finally:
        db.close()


def test_synthesize_repro_valueerror_fails(monkeypatch):
    run_id, _repo = _seed_run()
    _approve(run_id, "sandbox_provision")
    _stub_clone_only(monkeypatch)

    def boom(**kwargs):
        raise ValueError("cannot synthesize reproduction")

    monkeypatch.setattr("app.workers.tasks.synthesize_repro", boom)
    clone_and_index.run(run_id)
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        attempt = (
            db.query(ReproductionAttempt)
            .filter(ReproductionAttempt.run_id == run_id)
            .one()
        )
        assert run.status == "failed"
        assert "cannot synthesize reproduction" in (run.error or "")
        assert attempt.reproduced is False
    finally:
        db.close()


def test_stop_after_repro_is_not_successful(monkeypatch):
    run_id, _repo = _seed_run()
    _approve(run_id, "sandbox_provision")
    _stub_repro_pipeline(monkeypatch)
    monkeypatch.setattr(
        "app.workers.tasks.settings.autopatch_stop_after_repro",
        True,
    )

    def must_not_generate_patch(**kwargs):
        raise AssertionError("generate_patch must not be called")

    monkeypatch.setattr("app.workers.tasks.generate_patch", must_not_generate_patch)
    before = _stats()["successful"]
    clone_and_index.run(run_id)
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        attempt = (
            db.query(ReproductionAttempt)
            .filter(ReproductionAttempt.run_id == run_id)
            .one()
        )
        assert run.status == "failed"
        assert run.error == "stopped after reproduction"
        assert run.current_diff is None
        assert run.pr_url is None
        assert attempt.reproduced is True
    finally:
        db.close()
    assert _stats()["successful"] == before


def test_stale_clone_with_diff_awaits_patch_review():
    finished = _now()
    run = SandboxRun(
        id=611,
        status="running",
        pipeline_stage=STAGE_CLONE,
        repo="a/b",
        ref="main",
        current_diff="diff --git a/x b/x",
        finished_at=finished,
        duration_ms=10,
        started_at=finished - timedelta(seconds=10),
    )
    assert _claim_clone_stage(LockDB(run), run, datetime.now(timezone.utc)) is False
    assert run.status == "awaiting_patch_review"
    assert run.pipeline_stage == STAGE_PATCH_REVIEW
    assert run_state_is_valid(run)


def test_stale_clone_without_diff_fails():
    finished = _now()
    run = SandboxRun(
        id=612,
        status="running",
        pipeline_stage=STAGE_CLONE,
        repo="a/b",
        ref="main",
        finished_at=finished,
        duration_ms=10,
        started_at=finished - timedelta(seconds=10),
    )
    assert _claim_clone_stage(LockDB(run), run, datetime.now(timezone.utc)) is False
    assert run.status == "failed"
    assert run.error == "stale clone with no patch"
    assert run_state_is_valid(run)


def test_stats_ignore_completed_without_pr_url():
    db = SessionLocal()
    try:
        repo = _ensure_test_repository(db)
        before = _stats()["successful"]
        orphan = SandboxRun(
            status="completed",
            repo=repo.full_name,
            ref=repo.default_branch,
            pipeline_stage=STAGE_CLONE,
        )
        genuine = SandboxRun(
            status="completed",
            repo=repo.full_name,
            ref=repo.default_branch,
            pipeline_stage="pr",
            pr_url="https://github.com/a/b/pull/99",
        )
        db.add(orphan)
        db.add(genuine)
        db.commit()
    finally:
        db.close()
    after = _stats()["successful"]
    assert after == before + 1


def test_genuine_pr_completion_counts_successful(monkeypatch):
    run_id, _repo = _seed_run(
        status="awaiting_merge",
        current_diff="diff --git a/x b/x\n--- a/x\n+++ a/x\n",
        pipeline_stage="merge",
        source_sha=TEST_SOURCE_SHA,
    )
    _approve(run_id, "merge")
    _stub_pr_publish(monkeypatch)
    before = _stats()["successful"]
    open_github_pr.run(run_id)
    run = _run_after_clone(run_id)
    assert run.status == "completed"
    assert run.pr_url
    assert _stats()["successful"] == before + 1
