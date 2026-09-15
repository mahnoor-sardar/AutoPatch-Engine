from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import ApprovalGate, PatchAttempt, SandboxRun
from app.services.approval import (
    STAGE_CLONE,
    STAGE_PATCH_APPLY,
    STAGE_PATCH_REVIEW,
    STAGE_PR,
)
from app.workers.tasks import (
    _claim_apply_stage,
    _claim_clone_stage,
    _claim_pr_stage,
    _mark_running,
    apply_patch_and_verify,
    clone_and_index,
    run_state_is_valid,
)
from tests.test_worker import _ensure_test_repository


def _now():
    return datetime.now(timezone.utc)


class Query:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def with_for_update(self, *args, **kwargs):
        return self

    def one(self):
        if isinstance(self._result, list):
            return self._result[0]
        return self._result

    def first(self):
        if isinstance(self._result, list):
            return self._result[0] if self._result else None
        return self._result


class LockDB:
    def __init__(self, run, patches=None):
        self.run = run
        self.patches = patches or []

    def query(self, model):
        if model is PatchAttempt:
            return Query(self.patches)
        return Query(self.run)

    def commit(self):
        return None


def test_a_duplicate_clone_does_not_restart_completed():
    finished = _now()
    run = SandboxRun(
        id=1,
        status="completed",
        pipeline_stage=STAGE_CLONE,
        repo="a/b",
        ref="main",
        finished_at=finished,
        duration_ms=128113,
        started_at=finished - timedelta(seconds=128),
    )
    claimed = _claim_clone_stage(LockDB(run), run, _now())
    assert claimed is False
    assert run.status == "completed"
    assert run.finished_at == finished
    assert run_state_is_valid(run)


def test_a_clone_task_noop_on_completed(monkeypatch):
    db = SessionLocal()
    try:
        repo = _ensure_test_repository(db)
        finished = _now()
        run = SandboxRun(
            status="completed",
            repo=repo.full_name,
            ref=repo.default_branch,
            pipeline_stage=STAGE_CLONE,
            finished_at=finished,
            duration_ms=50,
            started_at=finished - timedelta(seconds=50),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        db.add(
            ApprovalGate(
                run_id=run.id,
                gate="sandbox_provision",
                status="approved",
                device_id="state-test",
            )
        )
        db.commit()
        run_id = run.id
    finally:
        db.close()

    def boom(*args, **kwargs):
        raise AssertionError("clone must not re-execute")

    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        boom,
    )
    clone_and_index.run(run_id)
    db = SessionLocal()
    try:
        again = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert again.status == "completed"
        assert again.pipeline_stage == STAGE_CLONE
        assert run_state_is_valid(again)
    finally:
        db.close()


def test_clone_and_index_does_not_provision_while_gate_pending(monkeypatch):
    db = SessionLocal()
    try:
        repo = _ensure_test_repository(db)
        run = SandboxRun(
            status="queued",
            repo=repo.full_name,
            ref=repo.default_branch,
            pipeline_stage="provision",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        db.add(
            ApprovalGate(
                run_id=run.id,
                gate="sandbox_provision",
                status="pending",
            )
        )
        db.commit()
        run_id = run.id
    finally:
        db.close()

    def boom(*args, **kwargs):
        raise AssertionError("clone must wait for sandbox_provision approval")

    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        boom,
    )
    try:
        clone_and_index.run(run_id)
    except RuntimeError as exc:
        assert "sandbox_provision" in str(exc)
        assert "approval" in str(exc)

    db = SessionLocal()
    try:
        again = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert again.status == "queued"
        assert again.e2b_sandbox_id is None
        assert again.pipeline_stage == "provision"
    finally:
        db.close()


def test_b_starting_stage_clears_old_timing():
    old_finish = _now() - timedelta(minutes=10)
    run = SandboxRun(
        id=1,
        status="awaiting_patch_review",
        pipeline_stage=STAGE_PATCH_REVIEW,
        repo="a/b",
        ref="main",
        current_diff="diff",
        finished_at=old_finish,
        duration_ms=128113,
        started_at=old_finish - timedelta(seconds=128),
    )
    started = _now()
    assert _claim_apply_stage(LockDB(run), run, started) is True
    assert run.status == "running"
    assert run.pipeline_stage == STAGE_PATCH_APPLY
    assert run.finished_at is None
    assert run.duration_ms is None
    assert run.started_at == started
    assert run_state_is_valid(run)


def test_b_mark_running_clears_finished_fields():
    run = SandboxRun(
        status="queued",
        pipeline_stage="provision",
        finished_at=_now(),
        duration_ms=99,
    )
    started = _now()
    _mark_running(run, STAGE_CLONE, started)
    assert run.status == "running"
    assert run.finished_at is None
    assert run.duration_ms is None
    assert run_state_is_valid(run)


def test_c_duplicate_patch_apply_does_not_leave_running():
    finished = _now()
    run = SandboxRun(
        id=1,
        status="awaiting_merge",
        pipeline_stage="merge",
        repo="a/b",
        ref="main",
        current_diff="diff",
        finished_at=finished,
        duration_ms=115000,
    )
    assert _claim_apply_stage(LockDB(run), run, _now()) is False
    assert run.status == "awaiting_merge"
    assert run_state_is_valid(run)


def test_c_stale_running_patch_apply_is_repaired():
    run = SandboxRun(
        id=1,
        status="running",
        pipeline_stage=STAGE_PATCH_APPLY,
        repo="a/b",
        ref="main",
        current_diff="diff",
        finished_at=_now(),
        duration_ms=115000,
        patch_attempts=1,
    )
    applied = PatchAttempt(
        run_id=1,
        attempt_number=1,
        diff="diff",
        status="applied",
    )
    assert _claim_apply_stage(LockDB(run, [applied]), run, _now()) is False
    assert run.status == "awaiting_merge"
    assert run.finished_at is not None
    assert run_state_is_valid(run)


def test_c_apply_task_noop_on_awaiting_merge(monkeypatch):
    db = SessionLocal()
    try:
        repo = _ensure_test_repository(db)
        finished = _now()
        run = SandboxRun(
            status="awaiting_merge",
            repo=repo.full_name,
            ref=repo.default_branch,
            pipeline_stage="merge",
            current_diff="diff",
            finished_at=finished,
            duration_ms=20,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        db.add(
            ApprovalGate(
                run_id=run.id,
                gate="patch_review",
                status="approved",
            )
        )
        db.commit()
        run_id = run.id
    finally:
        db.close()

    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("apply must not re-execute")),
    )
    apply_patch_and_verify.run(run_id)
    db = SessionLocal()
    try:
        again = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert again.status == "awaiting_merge"
        assert run_state_is_valid(again)
    finally:
        db.close()


def test_d_later_stage_not_overwritten_by_clone():
    finished = _now()
    run = SandboxRun(
        id=1,
        status="awaiting_patch_review",
        pipeline_stage=STAGE_PATCH_REVIEW,
        repo="a/b",
        ref="main",
        current_diff="diff",
        finished_at=finished,
        duration_ms=10,
    )
    assert _claim_clone_stage(LockDB(run), run, _now()) is False
    assert run.status == "awaiting_patch_review"
    assert run.pipeline_stage == STAGE_PATCH_REVIEW
    assert run_state_is_valid(run)


def test_d_clone_task_skips_later_stage(monkeypatch):
    db = SessionLocal()
    try:
        repo = _ensure_test_repository(db)
        finished = _now()
        run = SandboxRun(
            status="awaiting_patch_review",
            repo=repo.full_name,
            ref=repo.default_branch,
            pipeline_stage=STAGE_PATCH_REVIEW,
            current_diff="diff --git a/x b/x",
            finished_at=finished,
            duration_ms=10,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        db.add(
            ApprovalGate(
                run_id=run.id,
                gate="sandbox_provision",
                status="approved",
            )
        )
        db.commit()
        run_id = run.id
    finally:
        db.close()

    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("stale clone must not run")),
    )
    clone_and_index.run(run_id)
    db = SessionLocal()
    try:
        again = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert again.status == "awaiting_patch_review"
        assert again.pipeline_stage == STAGE_PATCH_REVIEW
        assert run_state_is_valid(again)
    finally:
        db.close()


def test_e_success_return_state_is_valid_after_stale_running_clone():
    run = SandboxRun(
        id=445,
        status="running",
        pipeline_stage=STAGE_CLONE,
        repo="a/b",
        ref="main",
        finished_at=_now() - timedelta(seconds=10),
        duration_ms=128113,
        started_at=_now(),
    )
    assert run_state_is_valid(run) is False
    assert _claim_clone_stage(LockDB(run), run, _now()) is False
    assert run.status == "completed"
    assert run_state_is_valid(run)


def test_e_failed_run_not_reset_to_running():
    run = SandboxRun(
        id=444,
        status="failed",
        pipeline_stage=STAGE_PATCH_APPLY,
        repo="a/b",
        ref="main",
        finished_at=_now(),
        duration_ms=151311,
        error="E2B git clone failed",
    )
    assert _claim_clone_stage(LockDB(run), run, _now()) is False
    assert _claim_apply_stage(LockDB(run), run, _now()) is False
    assert run.status == "failed"
    assert run_state_is_valid(run)


def test_pr_claim_does_not_restart_completed():
    run = SandboxRun(
        id=1,
        status="completed",
        pipeline_stage=STAGE_PR,
        pr_url="https://github.com/a/b/pull/1",
        finished_at=_now(),
        duration_ms=1,
    )
    assert _claim_pr_stage(LockDB(run), run, _now()) is False
    assert run.status == "completed"
    assert run_state_is_valid(run)


def test_crash_retry_running_clone_without_finished_at_may_reclaim():
    run = SandboxRun(
        id=1,
        status="running",
        pipeline_stage=STAGE_CLONE,
        repo="a/b",
        ref="main",
        started_at=_now() - timedelta(minutes=5),
        finished_at=None,
        duration_ms=None,
    )
    started = _now()
    assert _claim_clone_stage(LockDB(run), run, started) is True
    assert run.status == "running"
    assert run.finished_at is None
    assert run.started_at == started
    assert run_state_is_valid(run)
