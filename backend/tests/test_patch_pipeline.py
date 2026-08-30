from types import SimpleNamespace

from app.db import SessionLocal
from app.models import (
    ApprovalGate,
    AuditEvent,
    GitHubInstallation,
    PatchAttempt,
    ReproductionAttempt,
    Repository,
    SandboxRun,
)
from app.services.harness import ADDITIONAL_TESTS_SKIPPED, ReproductionResult
from app.workers.tasks import MAX_PATCH_ATTEMPTS, apply_patch_and_verify, clone_and_index


STACK_TRACE = """Traceback (most recent call last):
  File "backend/app/services/math.py", line 2, in calculate
    return 10 / 0
ZeroDivisionError: division by zero
"""

SOURCE_FILES = {
    "backend/app/services/math.py": """def calculate():
    return 10 / 0
"""
}


def _ensure_test_repository(db):
    repo = db.query(Repository).order_by(Repository.id).first()
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


def _seed_run(status="queued", **kwargs):
    db = SessionLocal()
    try:
        repo = _ensure_test_repository(db)
        run = SandboxRun(
            status=status,
            repo=repo.full_name,
            ref=repo.default_branch,
            stack_trace=STACK_TRACE,
            **kwargs,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id, repo.full_name
    finally:
        db.close()


def _approve(run_id, gate):
    db = SessionLocal()
    try:
        db.add(
            ApprovalGate(
                run_id=run_id,
                gate=gate,
                status="approved",
                device_id="test-device",
            )
        )
        db.commit()
    finally:
        db.close()


def _fake_sandbox():
    files = SimpleNamespace(write=lambda path, content: None)
    commands = SimpleNamespace(run=lambda *a, **k: SimpleNamespace(stdout="", stderr=""))
    return SimpleNamespace(
        sandbox_id="sbx-test",
        kill=lambda: None,
        files=files,
        commands=commands,
        write_file=lambda path, content: None,
        run=lambda *a, **k: SimpleNamespace(stdout="", stderr=""),
    )


def test_reproduced_bug_without_llm_does_not_complete(monkeypatch):
    run_id, _repo = _seed_run()
    _approve(run_id, "sandbox_provision")

    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        lambda **kwargs: (_fake_sandbox(), SOURCE_FILES),
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.install_project_dependencies",
        lambda sandbox: (0, "", ""),
    )
    monkeypatch.setattr(
        "app.workers.tasks.get_installation_token_sync",
        lambda installation_id: "test-token",
    )
    monkeypatch.setattr(
        "app.workers.tasks.run_reproduction_test",
        lambda sandbox, test_path, test_source, **kwargs: ReproductionResult(
            exit_code=1,
            stdout="",
            stderr="ZeroDivisionError",
        ),
    )
    from app.services.patcher import LlmNotConfigured

    def boom(**kwargs):
        raise LlmNotConfigured("LLM_API_KEY is not set")

    monkeypatch.setattr("app.workers.tasks.generate_patch", boom)
    clone_and_index.run(run_id)

    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.status == "failed"
        assert "LLM_API_KEY" in (run.error or "")
    finally:
        db.close()


def test_reproduced_bug_with_diff_awaits_review(monkeypatch):
    run_id, _repo = _seed_run()
    _approve(run_id, "sandbox_provision")
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        lambda **kwargs: (_fake_sandbox(), SOURCE_FILES),
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.install_project_dependencies",
        lambda sandbox: (0, "", ""),
    )
    monkeypatch.setattr(
        "app.workers.tasks.get_installation_token_sync",
        lambda installation_id: "test-token",
    )
    monkeypatch.setattr(
        "app.workers.tasks.run_reproduction_test",
        lambda sandbox, test_path, test_source, **kwargs: ReproductionResult(
            exit_code=1,
            stdout="",
            stderr="ZeroDivisionError",
        ),
    )
    monkeypatch.setattr(
        "app.workers.tasks.generate_patch",
        lambda **kwargs: "diff --git a/x b/x\n--- a/x\n+++ b/x\n",
    )
    monkeypatch.setattr("app.services.fcm.send_push", lambda *a, **k: "ok")
    clone_and_index.run(run_id)
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.status == "awaiting_patch_review"
        assert run.current_diff
        gate = (
            db.query(ApprovalGate)
            .filter(
                ApprovalGate.run_id == run_id,
                ApprovalGate.gate == "patch_review",
            )
            .order_by(ApprovalGate.id.desc())
            .first()
        )
        assert gate is not None
        assert gate.status == "pending"
    finally:
        db.close()


def _stub_repro_pipeline(monkeypatch):
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        lambda **kwargs: (_fake_sandbox(), SOURCE_FILES),
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.install_project_dependencies",
        lambda sandbox: (0, "", ""),
    )
    monkeypatch.setattr(
        "app.workers.tasks.get_installation_token_sync",
        lambda installation_id: "test-token",
    )
    monkeypatch.setattr(
        "app.workers.tasks.run_reproduction_test",
        lambda sandbox, test_path, test_source, **kwargs: ReproductionResult(
            exit_code=1,
            stdout="",
            stderr="ZeroDivisionError",
        ),
    )
    monkeypatch.setattr(
        "app.workers.tasks.generate_patch",
        lambda **kwargs: "diff --git a/x b/x\n--- a/x\n+++ b/x\n",
    )
    monkeypatch.setattr("app.services.fcm.send_push", lambda *a, **k: "ok")


def test_reproduced_bug_stores_gemini_diagnosis(monkeypatch):
    run_id, _repo = _seed_run()
    _approve(run_id, "sandbox_provision")
    _stub_repro_pipeline(monkeypatch)
    monkeypatch.setattr(
        "app.workers.tasks.diagnose_reproduction",
        lambda **kwargs: "calculate divides by zero",
    )
    clone_and_index.run(run_id)
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        event = (
            db.query(AuditEvent)
            .filter(
                AuditEvent.run_id == run_id,
                AuditEvent.action == "diagnosis",
            )
            .one()
        )
        assert run.status == "awaiting_patch_review"
        assert event.detail == "calculate divides by zero"
    finally:
        db.close()


def test_gemini_diagnosis_failure_does_not_change_run_state(monkeypatch):
    run_id, _repo = _seed_run()
    _approve(run_id, "sandbox_provision")
    _stub_repro_pipeline(monkeypatch)

    def boom(**kwargs):
        raise RuntimeError("gemini unavailable")

    monkeypatch.setattr("app.workers.tasks.diagnose_reproduction", boom)
    clone_and_index.run(run_id)
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        attempt = (
            db.query(ReproductionAttempt)
            .filter(ReproductionAttempt.run_id == run_id)
            .one()
        )
        assert run.status == "awaiting_patch_review"
        assert run.current_diff
        assert attempt.reproduced is True
        assert (
            db.query(AuditEvent)
            .filter(
                AuditEvent.run_id == run_id,
                AuditEvent.action == "diagnosis",
            )
            .count()
        ) == 0
    finally:
        db.close()


def test_stop_after_repro_never_calls_generate_patch(monkeypatch):
    run_id, _repo = _seed_run()
    _approve(run_id, "sandbox_provision")
    monkeypatch.setattr(
        "app.workers.tasks.settings.autopatch_stop_after_repro",
        True,
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        lambda **kwargs: (_fake_sandbox(), SOURCE_FILES),
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.install_project_dependencies",
        lambda sandbox: (0, "", ""),
    )
    monkeypatch.setattr(
        "app.workers.tasks.get_installation_token_sync",
        lambda installation_id: "test-token",
    )
    monkeypatch.setattr(
        "app.workers.tasks.run_reproduction_test",
        lambda sandbox, test_path, test_source, **kwargs: ReproductionResult(
            exit_code=1,
            stdout="",
            stderr="ZeroDivisionError",
        ),
    )

    def must_not_generate_patch(**kwargs):
        raise AssertionError("generate_patch must not be called")

    monkeypatch.setattr(
        "app.workers.tasks.generate_patch",
        must_not_generate_patch,
    )
    monkeypatch.setattr("app.services.fcm.send_push", lambda *a, **k: "ok")
    clone_and_index.run(run_id)

    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.status == "completed"
        assert run.current_diff is None
        assert run.pr_url is None
        assert run.patch_attempts == 0
        attempt = (
            db.query(ReproductionAttempt)
            .filter(ReproductionAttempt.run_id == run_id)
            .one()
        )
        assert attempt.reproduced is True
        assert attempt.diagnostic_path == "backend/app/services/math.py"
        assert (
            db.query(PatchAttempt)
            .filter(PatchAttempt.run_id == run_id)
            .count()
        ) == 0
        assert (
            db.query(ApprovalGate)
            .filter(
                ApprovalGate.run_id == run_id,
                ApprovalGate.gate == "patch_review",
            )
            .count()
        ) == 0
    finally:
        db.close()


def test_patch_retry_stops_at_max_attempts(monkeypatch):
    run_id, _repo = _seed_run(
        status="awaiting_patch_review",
        current_diff="diff --git a/x b/x\n",
        patch_attempts=MAX_PATCH_ATTEMPTS,
        pipeline_stage="patch_apply",
    )
    _approve(run_id, "patch_review")
    generated = []
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        lambda **kwargs: (_fake_sandbox(), SOURCE_FILES),
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.install_project_dependencies",
        lambda sandbox: (0, "", ""),
    )
    monkeypatch.setattr(
        "app.workers.tasks.get_installation_token_sync",
        lambda installation_id: "test-token",
    )
    monkeypatch.setattr(
        "app.workers.tasks.run_reproduction_test",
        lambda sandbox, test_path, test_source, **kwargs: ReproductionResult(
            exit_code=1,
            stdout="",
            stderr="still failing",
        ),
    )
    monkeypatch.setattr(
        "app.workers.tasks.generate_patch",
        lambda **kwargs: generated.append("diff") or "diff --git a/x b/x\n",
    )
    db = SessionLocal()
    try:
        db.add(
            PatchAttempt(
                run_id=run_id,
                attempt_number=MAX_PATCH_ATTEMPTS,
                diff="diff --git a/x b/x\n",
                status="pending_review",
            )
        )
        db.commit()
    finally:
        db.close()

    apply_patch_and_verify.run(run_id)
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.status == "failed"
        assert "exhausted" in (run.error or "")
        assert generated == []
        assert run.patch_attempts == MAX_PATCH_ATTEMPTS
    finally:
        db.close()


def _seed_apply_verify_run():
    run_id, _repo = _seed_run(
        status="awaiting_patch_review",
        current_diff="diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        patch_attempts=1,
        pipeline_stage="patch_review",
    )
    _approve(run_id, "patch_review")
    db = SessionLocal()
    try:
        db.add(
            PatchAttempt(
                run_id=run_id,
                attempt_number=1,
                diff="diff --git a/x b/x\n--- a/x\n+++ b/x\n",
                status="pending_review",
            )
        )
        db.add(
            ReproductionAttempt(
                run_id=run_id,
                stack_trace=STACK_TRACE,
                diagnostic_path="backend/app/services/math.py",
                diagnostic_name="calculate",
                diagnostic_line=2,
                test_path="tests/autopatch_repro_test.py",
                test_source="def test_repro(): pass\n",
                reproduced=True,
                exit_code=1,
                stderr="ZeroDivisionError",
            )
        )
        db.commit()
    finally:
        db.close()
    return run_id


def _stub_apply_verify(monkeypatch):
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        lambda **kwargs: (_fake_sandbox(), SOURCE_FILES),
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.install_project_dependencies",
        lambda sandbox: (0, "", ""),
    )
    monkeypatch.setattr(
        "app.workers.tasks.get_installation_token_sync",
        lambda installation_id: "test-token",
    )
    monkeypatch.setattr("app.services.fcm.send_push", lambda *a, **k: "ok")
    monkeypatch.setattr(
        "app.workers.tasks.run_reproduction_test",
        lambda sandbox, test_path, test_source, **kwargs: ReproductionResult(
            exit_code=0,
            stdout="1 passed",
            stderr="",
        ),
    )


def test_full_suite_failure_is_persisted_and_passed_to_retry(monkeypatch):
    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    seen = {}

    def capture(**kwargs):
        seen.update(kwargs)
        return "diff --git a/x b/x\n--- a/x\n+++ b/x\n"

    monkeypatch.setattr("app.workers.tasks.generate_patch", capture)
    monkeypatch.setattr(
        "app.workers.tasks.run_full_test_suite",
        lambda sandbox: ReproductionResult(
            exit_code=1,
            stdout="FAILED tests/test_other.py::test_something",
            stderr="AssertionError: expected 2",
        ),
    )
    apply_patch_and_verify.run(run_id)
    db = SessionLocal()
    try:
        failed = (
            db.query(PatchAttempt)
            .filter(PatchAttempt.run_id == run_id, PatchAttempt.attempt_number == 1)
            .one()
        )
        assert failed.status == "failed"
        assert "full test suite failed (exit 1)" in (failed.stderr or "")
        assert "FAILED tests/test_other.py::test_something" in (failed.stderr or "")
        assert "AssertionError: expected 2" in (failed.stderr or "")
        assert failed.stdout == "FAILED tests/test_other.py::test_something"
        stored = failed.stderr
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.status == "awaiting_patch_review"
        assert run.patch_attempts == 2
    finally:
        db.close()
    assert seen["previous_error"] == stored
    assert seen["stderr"] == stored
    assert seen["previous_error"] != ""


def test_full_suite_timeout_is_persisted_and_passed_to_retry(monkeypatch):
    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    seen = {}

    def capture(**kwargs):
        seen.update(kwargs)
        return "diff --git a/x b/x\n--- a/x\n+++ b/x\n"

    monkeypatch.setattr("app.workers.tasks.generate_patch", capture)
    monkeypatch.setattr(
        "app.workers.tasks.run_full_test_suite",
        lambda sandbox: ReproductionResult(
            exit_code=124,
            stdout="",
            stderr="TimeoutException: command timed out after 120 seconds",
        ),
    )
    apply_patch_and_verify.run(run_id)
    db = SessionLocal()
    try:
        failed = (
            db.query(PatchAttempt)
            .filter(PatchAttempt.run_id == run_id, PatchAttempt.attempt_number == 1)
            .one()
        )
        assert failed.status == "failed"
        assert "full test suite failed (exit 124)" in (failed.stderr or "")
        assert "TimeoutException: command timed out after 120 seconds" in (
            failed.stderr or ""
        )
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.patch_attempts == 2
        assert run.status == "awaiting_patch_review"
    finally:
        db.close()
    assert "TimeoutException" in seen["previous_error"]
    assert seen["stderr"] == seen["previous_error"]


def test_unexpected_repro_exception_fails_verification_and_feeds_retry(
    monkeypatch,
):
    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    seen = {}
    suite_calls = []

    def capture(**kwargs):
        seen.update(kwargs)
        return "diff --git a/x b/x\n--- a/x\n+++ b/x\n"

    monkeypatch.setattr("app.workers.tasks.generate_patch", capture)
    monkeypatch.setattr(
        "app.workers.tasks.run_reproduction_test",
        lambda sandbox, test_path, test_source, **kwargs: ReproductionResult(
            exit_code=1,
            stdout="FAILED tests/autopatch_repro_test.py",
            stderr="TypeError: unsupported operand type(s) for /",
            expected_exception="ZeroDivisionError",
        ),
    )
    monkeypatch.setattr(
        "app.workers.tasks.run_full_test_suite",
        lambda sandbox: suite_calls.append(sandbox)
        or ReproductionResult(exit_code=0, stdout="skipped", stderr=""),
    )
    apply_patch_and_verify.run(run_id)
    db = SessionLocal()
    try:
        failed = (
            db.query(PatchAttempt)
            .filter(PatchAttempt.run_id == run_id, PatchAttempt.attempt_number == 1)
            .one()
        )
        assert failed.status == "failed"
        assert "reproduction test failed (exit 1)" in (failed.stderr or "")
        assert "TypeError" in (failed.stderr or "")
        assert failed.stdout == "FAILED tests/autopatch_repro_test.py"
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.status == "awaiting_patch_review"
        assert run.patch_attempts == 2
    finally:
        db.close()
    assert suite_calls == []
    assert "TypeError" in seen["previous_error"]
    assert seen["stderr"] == seen["previous_error"]


def test_repro_collection_failure_fails_verification(monkeypatch):
    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    seen = {}

    def capture(**kwargs):
        seen.update(kwargs)
        return "diff --git a/x b/x\n--- a/x\n+++ b/x\n"

    monkeypatch.setattr("app.workers.tasks.generate_patch", capture)
    monkeypatch.setattr(
        "app.workers.tasks.run_reproduction_test",
        lambda sandbox, test_path, test_source, **kwargs: ReproductionResult(
            exit_code=2,
            stdout="",
            stderr="ERROR collecting tests/autopatch_repro_test.py",
            expected_exception="ZeroDivisionError",
        ),
    )
    monkeypatch.setattr(
        "app.workers.tasks.run_full_test_suite",
        lambda sandbox: ReproductionResult(exit_code=0, stdout="", stderr=""),
    )
    apply_patch_and_verify.run(run_id)
    db = SessionLocal()
    try:
        failed = (
            db.query(PatchAttempt)
            .filter(PatchAttempt.run_id == run_id, PatchAttempt.attempt_number == 1)
            .one()
        )
        assert failed.status == "failed"
        assert "reproduction test failed (exit 2)" in (failed.stderr or "")
        assert "ERROR collecting" in (failed.stderr or "")
    finally:
        db.close()
    assert "ERROR collecting" in seen["previous_error"]


def test_expected_exception_after_apply_is_reproduced_and_retries(monkeypatch):
    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    seen = {}
    suite_calls = []

    def capture(**kwargs):
        seen.update(kwargs)
        return "diff --git a/x b/x\n--- a/x\n+++ b/x\n"

    monkeypatch.setattr("app.workers.tasks.generate_patch", capture)
    monkeypatch.setattr(
        "app.workers.tasks.run_reproduction_test",
        lambda sandbox, test_path, test_source, **kwargs: ReproductionResult(
            exit_code=1,
            stdout="FAILED tests/autopatch_repro_test.py",
            stderr="ZeroDivisionError: division by zero",
            expected_exception="ZeroDivisionError",
        ),
    )
    monkeypatch.setattr(
        "app.workers.tasks.run_full_test_suite",
        lambda sandbox: suite_calls.append(sandbox)
        or ReproductionResult(exit_code=0, stdout="", stderr=""),
    )
    apply_patch_and_verify.run(run_id)
    db = SessionLocal()
    try:
        failed = (
            db.query(PatchAttempt)
            .filter(PatchAttempt.run_id == run_id, PatchAttempt.attempt_number == 1)
            .one()
        )
        assert failed.status == "failed"
        assert "ZeroDivisionError: division by zero" in (failed.stderr or "")
        assert "reproduction test failed" not in (failed.stderr or "")
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.status == "awaiting_patch_review"
        assert run.patch_attempts == 2
    finally:
        db.close()
    assert suite_calls == []
    assert seen["previous_error"] == "ZeroDivisionError: division by zero"


def test_clean_repro_still_runs_full_suite_and_reaches_merge(monkeypatch):
    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    generated = []
    monkeypatch.setattr(
        "app.workers.tasks.generate_patch",
        lambda **kwargs: generated.append(kwargs) or "unused",
    )
    monkeypatch.setattr(
        "app.workers.tasks.run_full_test_suite",
        lambda sandbox: ReproductionResult(
            exit_code=0,
            stdout="1 passed",
            stderr="",
        ),
    )
    apply_patch_and_verify.run(run_id)
    db = SessionLocal()
    try:
        applied = (
            db.query(PatchAttempt)
            .filter(PatchAttempt.run_id == run_id, PatchAttempt.attempt_number == 1)
            .one()
        )
        assert applied.status == "applied"
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.status == "awaiting_merge"
        assert run.patch_attempts == 1
    finally:
        db.close()
    assert generated == []


def test_skipped_additional_tests_reach_merge_without_claiming_suite_passed(
    monkeypatch,
):
    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    notices = []

    monkeypatch.setattr(
        "app.workers.tasks.notify_run_event",
        lambda db, run, title, body, extra=None: notices.append(body),
    )
    monkeypatch.setattr(
        "app.workers.tasks.run_full_test_suite",
        lambda sandbox: ReproductionResult(
            exit_code=0,
            stdout=ADDITIONAL_TESTS_SKIPPED,
            stderr="",
            ran_tests=False,
        ),
    )
    apply_patch_and_verify.run(run_id)
    db = SessionLocal()
    try:
        applied = (
            db.query(PatchAttempt)
            .filter(PatchAttempt.run_id == run_id, PatchAttempt.attempt_number == 1)
            .one()
        )
        assert applied.status == "applied"
        assert applied.stdout == ADDITIONAL_TESTS_SKIPPED
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.status == "awaiting_merge"
    finally:
        db.close()
    assert notices
    assert "no additional project tests were selected" in notices[0]
    assert "all tests passed" not in notices[0].lower()
