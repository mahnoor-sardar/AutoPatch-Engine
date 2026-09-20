from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import SandboxRun
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
    _finish,
    _owned_update,
    _renew_stage_lease,
    apply_patch_and_verify,
    clone_and_index,
    open_github_pr,
    run_state_is_valid,
)
from tests.test_f09_source_sha import TEST_SOURCE_SHA, _stub_pr_publish
from tests.test_patch_pipeline import (
    _approve,
    _fake_sandbox,
    _seed_apply_verify_run,
    _seed_run,
    _seed_verified_pr_records,
)
from tests.test_run_state import LockDB, _now
from tests.test_worker import _ensure_test_repository


def _utc(offset_seconds=0):
    return datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)


def _load(run_id):
    db = SessionLocal()
    try:
        return db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
    finally:
        db.close()


def _persist_running(stage, **kwargs):
    db = SessionLocal()
    try:
        repo = _ensure_test_repository(db)
        token = kwargs.pop("stage_owner_token", "a" * 32)
        lease = kwargs.pop("stage_lease_expires_at", _utc(60))
        started = kwargs.pop("started_at", _utc(-10))
        run = SandboxRun(
            status="running",
            repo=repo.full_name,
            ref=repo.default_branch,
            pipeline_stage=stage,
            started_at=started,
            finished_at=None,
            duration_ms=None,
            stage_owner_token=token,
            stage_lease_expires_at=lease,
            **kwargs,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id, token, started, lease
    finally:
        db.close()


def test_a_active_lease_blocks_duplicate_claim():
    started = _now() - timedelta(seconds=30)
    token = "b" * 32
    lease = _now() + timedelta(seconds=60)
    run = SandboxRun(
        id=1801,
        status="running",
        pipeline_stage=STAGE_CLONE,
        repo="a/b",
        ref="main",
        started_at=started,
        finished_at=None,
        stage_owner_token=token,
        stage_lease_expires_at=lease,
    )
    assert _claim_clone_stage(LockDB(run), run, _now()) is False
    assert run.started_at == started
    assert run.stage_owner_token == token
    assert run.stage_lease_expires_at == lease
    assert run.status == "running"
    assert run_state_is_valid(run)


def test_b_expired_lease_allows_reclaim():
    old_started = _now() - timedelta(minutes=5)
    old_token = "c" * 32
    old_lease = _now() - timedelta(seconds=1)
    run = SandboxRun(
        id=1802,
        status="running",
        pipeline_stage=STAGE_CLONE,
        repo="a/b",
        ref="main",
        started_at=old_started,
        finished_at=None,
        stage_owner_token=old_token,
        stage_lease_expires_at=old_lease,
    )
    started = _now()
    assert _claim_clone_stage(LockDB(run), run, started) is True
    assert run.stage_owner_token != old_token
    assert run.stage_owner_token
    assert run.stage_lease_expires_at > _now()
    assert run.started_at == started
    assert run.finished_at is None
    assert run_state_is_valid(run)


def test_c_null_lease_remains_crash_reclaimable():
    run = SandboxRun(
        id=1803,
        status="running",
        pipeline_stage=STAGE_CLONE,
        repo="a/b",
        ref="main",
        started_at=_now() - timedelta(minutes=5),
        finished_at=None,
        duration_ms=None,
        stage_owner_token=None,
        stage_lease_expires_at=None,
    )
    started = _now()
    assert _claim_clone_stage(LockDB(run), run, started) is True
    assert run.status == "running"
    assert run.finished_at is None
    assert run.started_at == started
    assert run.stage_owner_token
    assert run.stage_lease_expires_at is not None
    assert run_state_is_valid(run)


def test_d_wrong_owner_cannot_finish():
    run_id, token, started, _lease = _persist_running(
        STAGE_PR,
        pr_url="https://github.com/a/b/pull/9",
        source_sha=TEST_SOURCE_SHA,
    )
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert _finish(db, run, started, "completed", owner_token="ffff") is False
        db.commit()
        again = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert again.status == "running"
        assert again.pr_url == "https://github.com/a/b/pull/9"
        assert again.stage_owner_token == token
        assert again.finished_at is None
    finally:
        db.close()


def test_e_correct_owner_can_finish_and_clears_lease():
    run_id, token, started, _lease = _persist_running(STAGE_CLONE)
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert _finish(
            db, run, started, "awaiting_patch_review", owner_token=token
        ) is True
        db.commit()
        again = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert again.status == "awaiting_patch_review"
        assert again.stage_owner_token is None
        assert again.stage_lease_expires_at is None
        assert again.finished_at is not None
        assert run_state_is_valid(again)
    finally:
        db.close()


def test_f_renew_succeeds_for_current_owner():
    run_id, token, _started, old_lease = _persist_running(STAGE_CLONE)
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert _renew_stage_lease(db, run, token, stage=STAGE_CLONE) is True
        db.refresh(run)
        assert run.stage_lease_expires_at > old_lease
        assert run.stage_owner_token == token
    finally:
        db.close()


def test_g_renew_fails_after_reclaim():
    run_id, stale_token, _started, _lease = _persist_running(
        STAGE_CLONE,
        stage_lease_expires_at=_utc(-2),
    )
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert _claim_clone_stage(db, run, _now()) is True
        new_token = run.stage_owner_token
        assert new_token != stale_token
        assert _renew_stage_lease(db, run, stale_token, stage=STAGE_CLONE) is False
        db.refresh(run)
        assert run.stage_owner_token == new_token
    finally:
        db.close()


def test_h_duplicate_clone_delivery_does_not_start_second_clone(monkeypatch):
    run_id, _token, _started, _lease = _persist_running(STAGE_CLONE)
    _approve(run_id, "sandbox_provision")
    cloned = []

    def boom(**kwargs):
        cloned.append(kwargs)
        raise AssertionError("clone must not re-execute")

    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        boom,
    )
    monkeypatch.setattr(
        "app.workers.tasks.installation_token_for_repo",
        lambda *a, **k: "test-token",
    )
    monkeypatch.setattr("app.services.fcm.send_push", lambda *a, **k: "ok")
    clone_and_index.run(run_id)
    assert cloned == []
    again = _load(run_id)
    assert again.status == "running"
    assert again.e2b_sandbox_id is None
    assert again.pipeline_stage == STAGE_CLONE


def test_i_duplicate_apply_delivery_does_not_clone_or_apply(monkeypatch):
    apply_id = _seed_apply_verify_run()
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == apply_id).one()
        run.status = "running"
        run.pipeline_stage = STAGE_PATCH_APPLY
        run.finished_at = None
        run.duration_ms = None
        run.started_at = _utc(-5)
        run.stage_owner_token = "d" * 32
        run.stage_lease_expires_at = _utc(60)
        db.commit()
    finally:
        db.close()
    cloned = []
    applied = []
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        lambda **kwargs: cloned.append(kwargs) or (_fake_sandbox(), {}),
    )
    monkeypatch.setattr(
        "app.workers.tasks.apply_diff_in_sandbox",
        lambda *a, **k: applied.append(1) or (True, None),
    )
    apply_patch_and_verify.run(apply_id)
    assert cloned == []
    assert applied == []
    again = _load(apply_id)
    assert again.status == "running"
    assert again.pipeline_stage == STAGE_PATCH_APPLY


def test_j_duplicate_pr_delivery_does_not_push_or_create(monkeypatch):
    run_id, _repo = _seed_run(
        status="running",
        current_diff="diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        pipeline_stage=STAGE_PR,
        source_sha=TEST_SOURCE_SHA,
        finished_at=None,
        stage_owner_token="e" * 32,
        stage_lease_expires_at=_utc(60),
        started_at=_utc(-5),
    )
    _approve(run_id, "merge")
    _seed_verified_pr_records(run_id)
    cloned, pushed, prs = _stub_pr_publish(monkeypatch)
    open_github_pr.run(run_id)
    assert cloned == []
    assert pushed == []
    assert prs == []
    again = _load(run_id)
    assert again.status == "running"
    assert again.pr_url is None


def test_k_stale_worker_cannot_write_after_reclaim():
    run_id, stale_token, started, _lease = _persist_running(
        STAGE_CLONE,
        stage_lease_expires_at=_utc(-2),
        source_sha=None,
        e2b_sandbox_id=None,
        pr_url=None,
    )
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert _claim_clone_stage(db, run, _now()) is True
        owner = run.stage_owner_token
        assert owner != stale_token
        assert _owned_update(
            db,
            run,
            stale_token,
            e2b_sandbox_id="stale-sandbox",
            source_sha=TEST_SOURCE_SHA,
            pr_url="https://github.com/a/b/pull/stale",
        ) is False
        assert _finish(
            db, run, started, "failed", "stale", owner_token=stale_token
        ) is False
        db.commit()
        again = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert again.stage_owner_token == owner
        assert again.e2b_sandbox_id is None
        assert again.source_sha is None
        assert again.pr_url is None
        assert again.status == "running"
        assert again.finished_at is None
    finally:
        db.close()


def test_l_finished_at_stale_clone_still_repairs_without_reclaim():
    finished = _now()
    run = SandboxRun(
        id=1812,
        status="running",
        pipeline_stage=STAGE_CLONE,
        repo="a/b",
        ref="main",
        current_diff="diff --git a/x b/x",
        finished_at=finished,
        duration_ms=10,
        started_at=finished - timedelta(seconds=10),
        stage_owner_token="f" * 32,
        stage_lease_expires_at=_utc(-10),
    )
    assert _claim_clone_stage(LockDB(run), run, _now()) is False
    assert run.status == "awaiting_patch_review"
    assert run.pipeline_stage == STAGE_PATCH_REVIEW
    assert run_state_is_valid(run)


def test_m_waiting_states_remain_unclaimable_by_clone():
    finished = _now()
    run = SandboxRun(
        id=1813,
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
    assert _claim_apply_stage(LockDB(run), run, _now()) is True
    assert run.stage_owner_token
    assert run.stage_lease_expires_at is not None
    merge = SandboxRun(
        id=1814,
        status="awaiting_merge",
        pipeline_stage="merge",
        repo="a/b",
        ref="main",
        finished_at=finished,
    )
    assert _claim_apply_stage(LockDB(merge), merge, _now()) is False
    assert merge.status == "awaiting_merge"
    assert _claim_pr_stage(LockDB(merge), merge, _now()) is True
    assert merge.stage_owner_token


def test_k_stale_clone_task_does_not_persist_after_reclaim(monkeypatch):
    run_id, _repo = _seed_run()
    _approve(run_id, "sandbox_provision")
    reclaimed = {}

    def reclaim_then_clone(**kwargs):
        db = SessionLocal()
        try:
            run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
            reclaimed["stale"] = run.stage_owner_token
            run.stage_lease_expires_at = _utc(-2)
            db.commit()
            db.refresh(run)
            assert _claim_clone_stage(db, run, _now()) is True
            reclaimed["owner"] = run.stage_owner_token
        finally:
            db.close()
        return _fake_sandbox(), {"a.py": "x = 1\n"}

    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        reclaim_then_clone,
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.install_project_dependencies",
        lambda sandbox: (0, "", ""),
    )
    monkeypatch.setattr(
        "app.workers.tasks.installation_token_for_repo",
        lambda *a, **k: "test-token",
    )
    monkeypatch.setattr("app.services.fcm.send_push", lambda *a, **k: "ok")
    clone_and_index.run(run_id)
    again = _load(run_id)
    assert again.e2b_sandbox_id is None
    assert again.source_sha is None
    assert again.status == "running"
    assert again.stage_owner_token == reclaimed["owner"]
    assert again.stage_owner_token != reclaimed["stale"]
    assert again.finished_at is None


def test_idle_queued_claim_receives_owner_token():
    run = SandboxRun(
        id=1815,
        status="queued",
        pipeline_stage="provision",
        repo="a/b",
        ref="main",
    )
    assert _claim_clone_stage(LockDB(run), run, _now()) is True
    assert run.stage_owner_token
    assert len(run.stage_owner_token) == 32
    assert run.stage_lease_expires_at is not None
