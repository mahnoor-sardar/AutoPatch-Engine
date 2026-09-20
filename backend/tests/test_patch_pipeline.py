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

TEST_SOURCE_SHA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SEEDED_DIFF = (
    "diff --git a/backend/app/services/math.py b/backend/app/services/math.py\n"
    "--- a/backend/app/services/math.py\n"
    "+++ b/backend/app/services/math.py\n"
)
RETRY_DIFF = "diff --git a/y b/y\n--- a/y\n+++ b/y\n"


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
        ref = kwargs.pop("ref", repo.default_branch)
        run = SandboxRun(
            status=status,
            repo=repo.full_name,
            ref=ref,
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


def _seed_verified_pr_records(
    run_id,
    *,
    diagnostic_path="backend/app/services/math.py",
    test_path="tests/autopatch_repro_test.py",
    test_source="def test_repro(): pass\n",
    reproduced=True,
    exit_code=1,
    patch_status="applied",
    patch_stdout=None,
    current_diff=None,
):
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        diff = current_diff if current_diff is not None else (run.current_diff or "\n")
        db.add(
            ReproductionAttempt(
                run_id=run_id,
                stack_trace=STACK_TRACE,
                diagnostic_path=diagnostic_path,
                diagnostic_name="calculate",
                diagnostic_line=2,
                test_path=test_path,
                test_source=test_source,
                reproduced=reproduced,
                exit_code=exit_code,
                stderr="ZeroDivisionError",
            )
        )
        db.add(
            PatchAttempt(
                run_id=run_id,
                attempt_number=run.patch_attempts or 1,
                diff=diff,
                status=patch_status,
                stdout=patch_stdout,
            )
        )
        db.commit()
    finally:
        db.close()


def _fake_sandbox():
    def _run(command="", *a, **k):
        stdout = ""
        text = command if isinstance(command, str) else ""
        if "rev-parse" in text:
            stdout = TEST_SOURCE_SHA + "\n"
        return SimpleNamespace(stdout=stdout, stderr="", exit_code=0)

    files = SimpleNamespace(write=lambda path, content: None)
    commands = SimpleNamespace(run=_run)
    return SimpleNamespace(
        sandbox_id="sbx-test",
        kill=lambda: None,
        files=files,
        commands=commands,
        write_file=lambda path, content: None,
        run=_run,
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
        "app.workers.tasks.installation_token_for_repo",
        lambda *args, **kwargs: "test-token",
    )
    monkeypatch.setattr(
        "app.workers.tasks.run_reproduction_test",
        lambda sandbox, test_path, test_source, **kwargs: ReproductionResult(
            exit_code=1,
            stdout="",
            stderr="ZeroDivisionError: division by zero",
            expected_exception="ZeroDivisionError",
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
        "app.workers.tasks.installation_token_for_repo",
        lambda *args, **kwargs: "test-token",
    )
    monkeypatch.setattr(
        "app.workers.tasks.run_reproduction_test",
        lambda sandbox, test_path, test_source, **kwargs: ReproductionResult(
            exit_code=1,
            stdout="",
            stderr="ZeroDivisionError: division by zero",
            expected_exception="ZeroDivisionError",
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
        "app.workers.tasks.installation_token_for_repo",
        lambda *args, **kwargs: "test-token",
    )
    monkeypatch.setattr(
        "app.workers.tasks.run_reproduction_test",
        lambda sandbox, test_path, test_source, **kwargs: ReproductionResult(
            exit_code=1,
            stdout="",
            stderr="ZeroDivisionError: division by zero",
            expected_exception="ZeroDivisionError",
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
    seen = {}
    monkeypatch.setattr(
        "app.workers.tasks.generate_patch",
        lambda **kwargs: seen.update(kwargs)
        or "diff --git a/x b/x\n--- a/x\n+++ b/x\n",
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
    assert seen["diagnosis"] == "calculate divides by zero"


def test_gemini_diagnosis_failure_does_not_change_run_state(monkeypatch):
    run_id, _repo = _seed_run()
    _approve(run_id, "sandbox_provision")
    _stub_repro_pipeline(monkeypatch)

    def boom(**kwargs):
        raise RuntimeError("gemini unavailable")

    monkeypatch.setattr("app.workers.tasks.diagnose_reproduction", boom)
    seen = {}
    monkeypatch.setattr(
        "app.workers.tasks.generate_patch",
        lambda **kwargs: seen.update(kwargs)
        or "diff --git a/x b/x\n--- a/x\n+++ b/x\n",
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
    assert seen.get("diagnosis") is None


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
        "app.workers.tasks.installation_token_for_repo",
        lambda *args, **kwargs: "test-token",
    )
    monkeypatch.setattr(
        "app.workers.tasks.run_reproduction_test",
        lambda sandbox, test_path, test_source, **kwargs: ReproductionResult(
            exit_code=1,
            stdout="",
            stderr="ZeroDivisionError: division by zero",
            expected_exception="ZeroDivisionError",
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
        assert run.status == "failed"
        assert run.error == "stopped after reproduction"
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
        source_sha=TEST_SOURCE_SHA,
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
        "app.workers.tasks.installation_token_for_repo",
        lambda *args, **kwargs: "test-token",
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
        current_diff=SEEDED_DIFF,
        patch_attempts=1,
        pipeline_stage="patch_review",
        source_sha=TEST_SOURCE_SHA,
    )
    _approve(run_id, "patch_review")
    db = SessionLocal()
    try:
        db.add(
            PatchAttempt(
                run_id=run_id,
                attempt_number=1,
                diff=SEEDED_DIFF,
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
        db.add(
            AuditEvent(
                run_id=run_id,
                action="diagnosis",
                detail="calculate divides by zero",
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
        "app.workers.tasks.installation_token_for_repo",
        lambda *args, **kwargs: "test-token",
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


def _stub_failed_follow_on_suite(monkeypatch):
    """Clean repro from `_stub_apply_verify` still reaches generate_patch via a failed extra suite."""
    monkeypatch.setattr(
        "app.workers.tasks.run_full_test_suite",
        lambda sandbox: ReproductionResult(
            exit_code=1,
            stdout="FAILED tests/test_regression.py",
            stderr="AssertionError: still broken",
        ),
    )


def test_full_suite_failure_is_persisted_and_passed_to_retry(monkeypatch):
    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    seen = {}

    def capture(**kwargs):
        seen.update(kwargs)
        return RETRY_DIFF

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
    assert "backend/app/services/math.py" in seen["files"]
    assert seen["diagnosis"] == "calculate divides by zero"


def test_full_suite_timeout_is_persisted_and_passed_to_retry(monkeypatch):
    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    seen = {}

    def capture(**kwargs):
        seen.update(kwargs)
        return RETRY_DIFF

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
        return RETRY_DIFF

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
        return RETRY_DIFF

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
        return RETRY_DIFF

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


def test_skipped_additional_tests_do_not_reach_merge(monkeypatch):
    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    notices = []

    monkeypatch.setattr(
        "app.workers.tasks.notify_run_event",
        lambda db, run, title, body, extra=None: notices.append((title, body)),
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
    monkeypatch.setattr(
        "app.workers.tasks.generate_patch",
        lambda **kwargs: "diff --git a/y b/y\n--- a/y\n+++ b/y\n",
    )
    apply_patch_and_verify.run(run_id)
    db = SessionLocal()
    try:
        applied = (
            db.query(PatchAttempt)
            .filter(PatchAttempt.run_id == run_id, PatchAttempt.attempt_number == 1)
            .one()
        )
        assert applied.status == "failed"
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.status != "awaiting_merge"
    finally:
        db.close()
    assert not any(title == "Merge OTP required" for title, _body in notices)


def test_apply_check_failure_skips_tests_and_feeds_retry(monkeypatch):
    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    seen = {}
    repro_calls = []
    suite_calls = []

    def capture(**kwargs):
        seen.update(kwargs)
        return RETRY_DIFF

    monkeypatch.setattr(
        "app.workers.tasks.apply_diff_in_sandbox",
        lambda sandbox, diff, **kwargs: (
            False,
            "git apply --check failed (exit 1): corrupt",
        ),
    )
    monkeypatch.setattr("app.workers.tasks.generate_patch", capture)
    monkeypatch.setattr(
        "app.workers.tasks.run_reproduction_test",
        lambda *a, **k: repro_calls.append(a) or ReproductionResult(
            exit_code=0, stdout="", stderr=""
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
        assert "git apply --check failed (exit 1)" in (failed.stderr or "")
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.status == "awaiting_patch_review"
        assert run.patch_attempts == 2
    finally:
        db.close()
    assert repro_calls == []
    assert suite_calls == []
    assert "git apply --check failed" in seen["previous_error"]


def test_missing_repro_test_fails_verification_safely(monkeypatch):
    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    seen = {}
    monkeypatch.setattr(
        "app.workers.tasks.generate_patch",
        lambda **kwargs: seen.update(kwargs) or RETRY_DIFF,
    )
    db = SessionLocal()
    try:
        db.query(ReproductionAttempt).filter(
            ReproductionAttempt.run_id == run_id
        ).delete()
        db.commit()
    finally:
        db.close()
    apply_patch_and_verify.run(run_id)
    db = SessionLocal()
    try:
        failed = (
            db.query(PatchAttempt)
            .filter(PatchAttempt.run_id == run_id, PatchAttempt.attempt_number == 1)
            .one()
        )
        assert failed.status == "failed"
        assert "verification could not be completed" in (failed.stderr or "")
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.status == "awaiting_patch_review"
    finally:
        db.close()
    assert seen["previous_error"] == "verification could not be completed"


def test_identical_diff_does_not_requeue_review(monkeypatch):
    from app.workers.tasks import IDENTICAL_PATCH_ERROR

    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    _stub_failed_follow_on_suite(monkeypatch)
    generated = []

    def same_patch(**kwargs):
        generated.append(kwargs.get("previous_error"))
        return SEEDED_DIFF

    monkeypatch.setattr("app.workers.tasks.generate_patch", same_patch)
    apply_patch_and_verify.run(run_id)
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        pending = (
            db.query(ApprovalGate)
            .filter(
                ApprovalGate.run_id == run_id,
                ApprovalGate.gate == "patch_review",
                ApprovalGate.status == "pending",
            )
            .count()
        )
        failed = (
            db.query(PatchAttempt)
            .filter(
                PatchAttempt.run_id == run_id,
                PatchAttempt.status == "failed",
                PatchAttempt.stderr == IDENTICAL_PATCH_ERROR,
            )
            .count()
        )
        assert pending == 0
        assert run.status == "failed"
        assert "exhausted" in (run.error or "")
        assert run.patch_attempts == MAX_PATCH_ATTEMPTS
        assert failed == MAX_PATCH_ATTEMPTS - 1
    finally:
        db.close()
    assert generated
    assert IDENTICAL_PATCH_ERROR in generated


def test_trailing_whitespace_diff_is_not_identical_retry(monkeypatch):
    from app.workers.tasks import IDENTICAL_PATCH_ERROR

    spaced = SEEDED_DIFF + "+fixed  \n"
    run_id = _seed_apply_verify_run()
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        run.current_diff = SEEDED_DIFF + "+fixed\n"
        record = (
            db.query(PatchAttempt)
            .filter(PatchAttempt.run_id == run_id)
            .order_by(PatchAttempt.id.desc())
            .first()
        )
        record.diff = run.current_diff
        db.commit()
    finally:
        db.close()
    _stub_apply_verify(monkeypatch)
    _stub_failed_follow_on_suite(monkeypatch)
    monkeypatch.setattr(
        "app.workers.tasks.generate_patch",
        lambda **kwargs: spaced,
    )
    apply_patch_and_verify.run(run_id)
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        identical = (
            db.query(PatchAttempt)
            .filter(
                PatchAttempt.run_id == run_id,
                PatchAttempt.stderr == IDENTICAL_PATCH_ERROR,
            )
            .count()
        )
        pending = (
            db.query(ApprovalGate)
            .filter(
                ApprovalGate.run_id == run_id,
                ApprovalGate.gate == "patch_review",
                ApprovalGate.status == "pending",
            )
            .count()
        )
        assert identical == 0
        assert pending == 1
        assert run.status == "awaiting_patch_review"
        assert run.current_diff == spaced
    finally:
        db.close()


def test_retry_persists_reported_token_usage(monkeypatch):
    from app.services.patcher import PatchGenerationResult

    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    _stub_failed_follow_on_suite(monkeypatch)
    seen = {}

    def capture(**kwargs):
        seen.update(kwargs)
        return PatchGenerationResult(
            diff=RETRY_DIFF,
            tokens_used=42,
        )

    monkeypatch.setattr("app.workers.tasks.generate_patch", capture)
    apply_patch_and_verify.run(run_id)
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.llm_tokens_used == 42
        assert run.status == "awaiting_patch_review"
        assert run.patch_attempts == 2
        pending = (
            db.query(ApprovalGate)
            .filter(
                ApprovalGate.run_id == run_id,
                ApprovalGate.gate == "patch_review",
                ApprovalGate.status == "pending",
            )
            .count()
        )
        assert pending == 1
    finally:
        db.close()
    assert seen["tokens_used"] == 0


def test_retry_does_not_invent_usage_when_provider_omits_it(monkeypatch):
    from app.services.patcher import PatchGenerationResult

    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    _stub_failed_follow_on_suite(monkeypatch)
    monkeypatch.setattr(
        "app.workers.tasks.generate_patch",
        lambda **kwargs: PatchGenerationResult(
            diff=RETRY_DIFF,
            tokens_used=None,
        ),
    )
    apply_patch_and_verify.run(run_id)
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.llm_tokens_used == 0
        assert run.status == "awaiting_patch_review"
    finally:
        db.close()


def test_token_budget_exceeded_skips_generate(monkeypatch):
    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    _stub_failed_follow_on_suite(monkeypatch)
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        run.llm_tokens_used = 50_000
        db.commit()
    finally:
        db.close()
    generated = []
    monkeypatch.setattr(
        "app.workers.tasks.settings.llm_token_budget",
        50_000,
    )
    monkeypatch.setattr(
        "app.workers.tasks.generate_patch",
        lambda **kwargs: generated.append(kwargs) or "unused",
    )
    apply_patch_and_verify.run(run_id)
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.status == "failed"
        assert "token budget" in (run.error or "")
        pending = (
            db.query(ApprovalGate)
            .filter(
                ApprovalGate.run_id == run_id,
                ApprovalGate.gate == "patch_review",
                ApprovalGate.status == "pending",
            )
            .count()
        )
        assert pending == 0
    finally:
        db.close()
    assert generated == []


def test_llm_timeout_feeds_retry_then_exhausts(monkeypatch):
    from app.services.patcher import LlmRequestTimeout

    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    _stub_failed_follow_on_suite(monkeypatch)
    errors = []

    def boom(**kwargs):
        errors.append(kwargs.get("previous_error"))
        raise LlmRequestTimeout("LLM request timed out")

    monkeypatch.setattr("app.workers.tasks.generate_patch", boom)
    apply_patch_and_verify.run(run_id)
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        timed_out = (
            db.query(PatchAttempt)
            .filter(
                PatchAttempt.run_id == run_id,
                PatchAttempt.status == "failed",
            )
            .all()
        )
        pending = (
            db.query(ApprovalGate)
            .filter(
                ApprovalGate.run_id == run_id,
                ApprovalGate.gate == "patch_review",
                ApprovalGate.status == "pending",
            )
            .count()
        )
        assert run.status == "failed"
        assert pending == 0
        assert run.patch_attempts == MAX_PATCH_ATTEMPTS
        assert any("timed out" in (row.stderr or "") for row in timed_out)
    finally:
        db.close()
    assert errors
    assert "LLM request timed out" in errors[1:]


def test_empty_diff_is_not_queued(monkeypatch):
    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    _stub_failed_follow_on_suite(monkeypatch)
    monkeypatch.setattr(
        "app.workers.tasks.generate_patch",
        lambda **kwargs: "   \n",
    )
    apply_patch_and_verify.run(run_id)
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        pending = (
            db.query(ApprovalGate)
            .filter(
                ApprovalGate.run_id == run_id,
                ApprovalGate.gate == "patch_review",
                ApprovalGate.status == "pending",
            )
            .count()
        )
        assert pending == 0
        assert run.status == "failed"
        assert run.current_diff.startswith(
            "diff --git a/backend/app/services/math.py"
        )
    finally:
        db.close()
