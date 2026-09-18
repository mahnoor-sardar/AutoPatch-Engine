from types import SimpleNamespace

from app.db import SessionLocal
from app.models import (
    ApprovalGate,
    GitHubInstallation,
    ReproductionAttempt,
    Repository,
    SandboxRun,
)
from app.workers.tasks import _clip_verify_output, clone_and_index


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


def test_worker_persists_reproduction_attempt(monkeypatch):
    db = SessionLocal()

    try:
        repo = _ensure_test_repository(db)

        run = SandboxRun(
            status="queued",
            repo=repo.full_name,
            ref=repo.default_branch,
            stack_trace=STACK_TRACE,
        )

        db.add(run)
        db.commit()
        db.refresh(run)

        gate = ApprovalGate(
            run_id=run.id,
            gate="sandbox_provision",
            status="approved",
            device_id="worker-test-device",
        )

        db.add(gate)
        db.commit()

        run_id = run.id

    finally:
        db.close()

    fake_sandbox = SimpleNamespace(
        sandbox_id="worker-test-sandbox",
        kill=lambda: None,
        files=SimpleNamespace(write=lambda *a, **k: None),
        commands=SimpleNamespace(
            run=lambda *a, **k: SimpleNamespace(
                stdout="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n",
                stderr="",
            )
        ),
        write_file=lambda *a, **k: None,
        run=lambda *a, **k: SimpleNamespace(
            stdout="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n",
            stderr="",
        ),
    )

    def fake_clone_and_read_sources_in_sandbox(
        clone_url,
        ref,
        token,
        sha=None,
    ):
        return fake_sandbox, SOURCE_FILES

    class FakeResult:
        exit_code = 1
        stdout = "1 failed"
        stderr = "ZeroDivisionError: division by zero"
        reproduced = True

    def fake_run_reproduction_test(
        sandbox,
        test_path,
        test_source,
        **kwargs,
    ):
        return FakeResult()

    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        fake_clone_and_read_sources_in_sandbox,
    )

    monkeypatch.setattr(
        "app.workers.tasks.installation_token_for_repo",
        lambda *args, **kwargs: "test-token",
    )

    monkeypatch.setattr(
        "app.workers.tasks.run_reproduction_test",
        fake_run_reproduction_test,
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.install_project_dependencies",
        lambda sandbox: (0, "", ""),
    )
    monkeypatch.setattr(
        "app.workers.tasks.generate_patch",
        lambda **kwargs: "diff --git a/x b/x\n--- a/x\n+++ b/x\n",
    )
    monkeypatch.setattr("app.services.fcm.send_push", lambda *a, **k: "ok")

    clone_and_index.run(run_id)

    db = SessionLocal()

    try:
        attempt = (
            db.query(ReproductionAttempt)
            .filter(
                ReproductionAttempt.run_id == run_id
            )
            .one()
        )

        run = (
            db.query(SandboxRun)
            .filter(SandboxRun.id == run_id)
            .one()
        )

        assert run.status == "awaiting_patch_review"

        assert attempt.diagnostic_path == (
            "backend/app/services/math.py"
        )

        assert attempt.diagnostic_name == "calculate"

        assert attempt.exit_code == 1

        assert attempt.reproduced is True

        assert (
            attempt.test_path
            == "tests/autopatch_repro_test.py"
        )

        assert "calculate()" in attempt.test_source

    finally:
        db.close()


def test_clip_verify_output_sanitizes_before_persist():
    raw = (
        'failed {"api_key":"verify-secret-value"} '
        "Authorization: Bearer ordinary-secret-token"
    )
    cleaned = _clip_verify_output(raw)
    assert "verify-secret-value" not in cleaned
    assert "ordinary-secret-token" not in cleaned
    assert "[REDACTED]" in cleaned

    db = SessionLocal()
    try:
        run = SandboxRun(status="failed", repo="a/b", ref="main")
        db.add(run)
        db.commit()
        db.refresh(run)
        attempt = ReproductionAttempt(
            run_id=run.id,
            stack_trace="Error",
            stdout=_clip_verify_output('api_key=stored-stdout-secret'),
            stderr=_clip_verify_output('{"secret": "stored-stderr-secret"}'),
            reproduced=False,
        )
        db.add(attempt)
        db.commit()
        db.refresh(attempt)
        assert "stored-stdout-secret" not in (attempt.stdout or "")
        assert "stored-stderr-secret" not in (attempt.stderr or "")
        assert "[REDACTED]" in attempt.stdout
        assert "[REDACTED]" in attempt.stderr
    finally:
        db.close()