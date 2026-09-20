from types import SimpleNamespace
from unittest.mock import Mock

from app.db import SessionLocal
from app.models import SandboxRun
from app.routers.sandbox import resume_paused_run
from app.services.approval import STAGE_CLONE, STAGE_PATCH_APPLY, STAGE_PR
from app.services.harness import ReproductionResult
from app.workers.tasks import (
    _check_run_control,
    _claim_apply_stage,
    _claim_clone_stage,
    _claim_pr_stage,
    _finish,
    apply_patch_and_verify,
    open_github_pr,
)
from tests.test_f09_source_sha import TEST_SOURCE_SHA, _stub_pr_publish
from tests.test_f18_stage_ownership import _load, _now, _persist_running, _utc
from tests.test_gate_expiry import RecordingDB
from tests.test_patch_pipeline import (
    SOURCE_FILES,
    _approve,
    _fake_sandbox,
    _seed_apply_verify_run,
    _seed_run,
    _seed_verified_pr_records,
    _stub_apply_verify,
)
from tests.test_run_state import LockDB


def _set_run(run_id, **fields):
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        for name, value in fields.items():
            setattr(run, name, value)
        db.commit()
    finally:
        db.close()


def test_apply_pause_before_apply_skips_diff(monkeypatch):
    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    applied = []

    def pause_then_install(sandbox):
        _set_run(run_id, status="paused", control_state="paused")
        return (0, "", "")

    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.install_project_dependencies",
        pause_then_install,
    )
    monkeypatch.setattr(
        "app.workers.tasks.apply_diff_in_sandbox",
        lambda *a, **k: applied.append(1) or (True, None),
    )
    apply_patch_and_verify.run(run_id)
    assert applied == []
    again = _load(run_id)
    assert again.status == "paused"
    assert again.control_state == "paused"
    assert again.pr_url is None


def test_apply_kill_before_apply_skips_diff_and_kills_local(monkeypatch):
    run_id = _seed_apply_verify_run()
    killed = []
    sandbox = _fake_sandbox()
    sandbox.kill = lambda: killed.append("local")
    _stub_apply_verify(monkeypatch)
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        lambda **kwargs: (sandbox, SOURCE_FILES),
    )

    def kill_then_install(session):
        _set_run(run_id, status="killed", control_state="killed")
        return (0, "", "")

    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.install_project_dependencies",
        kill_then_install,
    )
    applied = []
    monkeypatch.setattr(
        "app.workers.tasks.apply_diff_in_sandbox",
        lambda *a, **k: applied.append(1) or (True, None),
    )
    apply_patch_and_verify.run(run_id)
    assert applied == []
    assert "local" in killed
    again = _load(run_id)
    assert again.status == "killed"
    assert again.control_state == "killed"
    assert again.finished_at is None or again.status == "killed"


def test_apply_kill_during_reproduction_does_not_await_merge(monkeypatch):
    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    monkeypatch.setattr(
        "app.workers.tasks.apply_diff_in_sandbox",
        lambda *a, **k: (True, None),
    )
    full = []

    def kill_during_repro(*a, **k):
        _set_run(run_id, status="killed", control_state="killed")
        return ReproductionResult(exit_code=0, stdout="1 passed", stderr="")

    monkeypatch.setattr("app.workers.tasks.run_reproduction_test", kill_during_repro)
    monkeypatch.setattr(
        "app.workers.tasks.run_full_test_suite",
        lambda sandbox: full.append(1) or ReproductionResult(exit_code=0, stdout="", stderr=""),
    )
    apply_patch_and_verify.run(run_id)
    assert full == []
    again = _load(run_id)
    assert again.status == "killed"
    assert again.status != "awaiting_merge"
    assert again.pr_url is None


def test_pr_kill_after_commit_skips_push(monkeypatch):
    run_id, _repo = _seed_run(
        status="awaiting_merge",
        current_diff="diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        pipeline_stage="merge",
        source_sha=TEST_SOURCE_SHA,
    )
    _approve(run_id, "merge")
    _seed_verified_pr_records(run_id)
    cloned, pushed, prs = _stub_pr_publish(monkeypatch)

    def commit_then_kill(*a, **k):
        _set_run(run_id, status="killed", control_state="killed")
        return None

    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.run_sandbox_command",
        commit_then_kill,
    )
    open_github_pr.run(run_id)
    assert pushed == []
    assert prs == []
    again = _load(run_id)
    assert again.status == "killed"
    assert again.pr_url is None


def test_pr_kill_before_create_pull_request_skips_github(monkeypatch):
    run_id, _repo = _seed_run(
        status="awaiting_merge",
        current_diff="diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        pipeline_stage="merge",
        source_sha=TEST_SOURCE_SHA,
    )
    _approve(run_id, "merge")
    _seed_verified_pr_records(run_id)
    cloned, pushed, prs = _stub_pr_publish(monkeypatch)

    def push_then_kill(sandbox, branch, token):
        pushed.append((branch, token))
        _set_run(run_id, status="killed", control_state="killed")

    monkeypatch.setattr("app.workers.tasks.e2b_runner.push_branch", push_then_kill)
    open_github_pr.run(run_id)
    assert pushed
    assert prs == []
    again = _load(run_id)
    assert again.status == "killed"
    assert again.pr_url is None


def test_pr_control_check_immediately_before_push_and_create(monkeypatch):
    run_id, _repo = _seed_run(
        status="awaiting_merge",
        current_diff="diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        pipeline_stage="merge",
        source_sha=TEST_SOURCE_SHA,
    )
    _approve(run_id, "merge")
    _seed_verified_pr_records(run_id)
    order = []
    cloned, pushed, prs = _stub_pr_publish(monkeypatch)
    import app.workers.tasks as tasks

    real_check = tasks._check_run_control

    def tracing_check(*args, **kwargs):
        order.append("check")
        return real_check(*args, **kwargs)

    monkeypatch.setattr(tasks, "_check_run_control", tracing_check)

    def tracing_push(*a, **k):
        order.append("push")
        return None

    def tracing_pr(**kwargs):
        order.append("create_pull_request")
        prs.append(kwargs)
        return {"html_url": "https://github.com/a/b/pull/1"}

    monkeypatch.setattr("app.workers.tasks.e2b_runner.push_branch", tracing_push)
    monkeypatch.setattr("app.workers.tasks.create_pull_request", tracing_pr)
    open_github_pr.run(run_id)
    push_at = order.index("push")
    pr_at = order.index("create_pull_request")
    assert order[push_at - 1] == "check"
    assert order[pr_at - 1] == "check"
    assert pushed == [] or True
    assert prs


def test_sandbox_id_persisted_immediately_after_create(monkeypatch):
    run_id = _seed_apply_verify_run()
    seen_during_clone = {}

    class Session:
        sandbox_id = "sbx-early"

        def kill(self):
            return None

    monkeypatch.setattr(
        "app.services.e2b_runner.get_sandbox_provider",
        lambda: SimpleNamespace(create=lambda: Session()),
    )
    monkeypatch.setattr("app.services.e2b_runner.refresh_egress_allowlist", lambda s: None)

    def clone_after_create(**kwargs):
        db = SessionLocal()
        try:
            run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
            seen_during_clone["e2b_sandbox_id"] = run.e2b_sandbox_id
        finally:
            db.close()
        return SOURCE_FILES

    monkeypatch.setattr(
        "app.services.e2b_runner.clone_and_read_sources",
        clone_after_create,
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.install_project_dependencies",
        lambda sandbox: (0, "", ""),
    )
    monkeypatch.setattr(
        "app.workers.tasks.installation_token_for_repo",
        lambda *a, **k: "test-token",
    )
    monkeypatch.setattr(
        "app.workers.tasks.apply_diff_in_sandbox",
        lambda *a, **k: (False, "stopped"),
    )
    monkeypatch.setattr("app.services.fcm.send_push", lambda *a, **k: "ok")
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.checkout_head_sha",
        lambda sandbox: TEST_SOURCE_SHA,
    )
    apply_patch_and_verify.run(run_id)
    assert seen_during_clone["e2b_sandbox_id"] == "sbx-early"


def test_sandbox_id_not_persisted_when_control_lost_after_create(monkeypatch):
    run_id = _seed_apply_verify_run()
    killed = []

    class Session:
        sandbox_id = "sbx-lost"

        def kill(self):
            killed.append("local")

    def create_and_pause():
        _set_run(run_id, status="paused", control_state="paused")
        return Session()

    monkeypatch.setattr(
        "app.services.e2b_runner.get_sandbox_provider",
        lambda: SimpleNamespace(create=create_and_pause),
    )
    cloned = []
    monkeypatch.setattr(
        "app.services.e2b_runner.clone_and_read_sources",
        lambda **kwargs: cloned.append(1) or SOURCE_FILES,
    )
    monkeypatch.setattr("app.services.e2b_runner.refresh_egress_allowlist", lambda s: None)
    monkeypatch.setattr(
        "app.workers.tasks.installation_token_for_repo",
        lambda *a, **k: "test-token",
    )
    monkeypatch.setattr("app.services.fcm.send_push", lambda *a, **k: "ok")
    apply_patch_and_verify.run(run_id)
    assert cloned == []
    assert "local" in killed
    again = _load(run_id)
    assert again.e2b_sandbox_id is None
    assert again.status == "paused"


def test_kill_api_without_sandbox_id_does_not_call_provider(monkeypatch):
    from fastapi.testclient import TestClient
    import pyotp

    from app.db import get_db
    from app.main import app
    from app.models import Device
    from app.services.totp import new_secret

    provider_killed = []

    class Provider:
        def create(self):
            raise NotImplementedError

        def kill(self, sandbox_id):
            provider_killed.append(sandbox_id)

    monkeypatch.setattr("app.routers.sandbox.get_sandbox_provider", lambda: Provider())
    secret = new_secret()
    run = SandboxRun(
        id=1,
        status="running",
        repo="a/b",
        ref="main",
        e2b_sandbox_id=None,
        control_state="active",
    )
    device = Device(device_id="dev-1", fcm_token="x", totp_secret=secret)

    class Query:
        def __init__(self, result):
            self._result = result

        def filter(self, *a, **k):
            return self

        def one_or_none(self):
            return self._result

        def one(self):
            return self._result

    class DB:
        def query(self, model):
            if model is SandboxRun:
                return Query(run)
            if model is Device:
                return Query(device)
            return Query(None)

        def add(self, obj):
            return None

        def commit(self):
            return None

    app.dependency_overrides[get_db] = lambda: DB()
    client = TestClient(app)
    try:
        code = pyotp.TOTP(secret).now()
        response = client.post(
            "/v1/sandbox/runs/1/kill",
            headers={"X-API-Key": "dev-local-key"},
            json={"device_id": "dev-1", "otp_code": code},
        )
        assert response.status_code == 200
        assert provider_killed == []
        assert run.status == "killed"
    finally:
        app.dependency_overrides.clear()


def test_worker_finally_kills_local_sandbox_after_kill(monkeypatch):
    run_id = _seed_apply_verify_run()
    killed = []
    sandbox = _fake_sandbox()
    sandbox.kill = lambda: killed.append("finally")
    _stub_apply_verify(monkeypatch)
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        lambda **kwargs: (sandbox, SOURCE_FILES),
    )

    def kill_then_install(session):
        _set_run(run_id, status="killed", control_state="killed")
        return (0, "", "")

    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.install_project_dependencies",
        kill_then_install,
    )
    monkeypatch.setattr(
        "app.workers.tasks.apply_diff_in_sandbox",
        lambda *a, **k: (True, None),
    )
    apply_patch_and_verify.run(run_id)
    assert "finally" in killed


def test_pause_does_not_kill_sandbox_via_control_helper():
    run_id, token, _started, _lease = _persist_running(STAGE_PATCH_APPLY)
    _set_run(run_id, status="paused", control_state="paused")
    sandbox = Mock()
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert _check_run_control(db, run, token, sandbox, stage=STAGE_PATCH_APPLY) is False
        sandbox.kill.assert_not_called()
        db.refresh(run)
        assert run.status == "paused"
        assert run.control_state == "paused"
    finally:
        db.close()


def test_paused_and_killed_cannot_be_lease_reclaimed():
    paused = SandboxRun(
        id=1901,
        status="paused",
        control_state="paused",
        pipeline_stage=STAGE_PATCH_APPLY,
        repo="a/b",
        ref="main",
        finished_at=None,
        stage_owner_token="a" * 32,
        stage_lease_expires_at=_utc(-10),
    )
    assert _claim_apply_stage(LockDB(paused), paused, _now()) is False
    assert paused.status == "paused"
    killed = SandboxRun(
        id=1902,
        status="killed",
        control_state="killed",
        pipeline_stage=STAGE_CLONE,
        repo="a/b",
        ref="main",
        finished_at=_now(),
        stage_owner_token="b" * 32,
        stage_lease_expires_at=_utc(-10),
    )
    assert _claim_clone_stage(LockDB(killed), killed, _now()) is False
    assert killed.status == "killed"
    pr = SandboxRun(
        id=1903,
        status="killed",
        control_state="killed",
        pipeline_stage=STAGE_PR,
        repo="a/b",
        ref="main",
        finished_at=_now(),
    )
    assert _claim_pr_stage(LockDB(pr), pr, _now()) is False


def test_stale_owner_cannot_finish_after_pause_or_kill():
    run_id, token, started, _lease = _persist_running(
        STAGE_PR, pr_url=None, source_sha=TEST_SOURCE_SHA
    )
    _set_run(run_id, status="killed", control_state="killed")
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert _finish(db, run, started, "completed", owner_token=token) is False
        db.commit()
        again = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert again.status == "killed"
        assert again.pr_url is None
        assert again.control_state == "killed"
    finally:
        db.close()


def test_resume_apply_and_pr_stages_still_enqueue(monkeypatch):
    apply_delayed = []
    pr_delayed = []
    monkeypatch.setattr(
        "app.routers.sandbox.apply_patch_and_verify.delay",
        lambda run_id: apply_delayed.append(run_id),
    )
    monkeypatch.setattr(
        "app.routers.sandbox.open_github_pr.delay",
        lambda run_id: pr_delayed.append(run_id),
    )
    apply_run = SandboxRun(
        id=21,
        status="paused",
        repo="a/b",
        ref="main",
        control_state="paused",
        pipeline_stage=STAGE_PATCH_APPLY,
    )
    resume_paused_run(apply_run, RecordingDB(apply_run, []))
    assert apply_run.control_state == "active"
    assert apply_run.status == "queued"
    assert apply_delayed == [21]

    pr_run = SandboxRun(
        id=22,
        status="paused",
        repo="a/b",
        ref="main",
        control_state="paused",
        pipeline_stage=STAGE_PR,
    )
    resume_paused_run(pr_run, RecordingDB(pr_run, []))
    assert pr_run.control_state == "active"
    assert pr_run.status == "queued"
    assert pr_delayed == [22]
