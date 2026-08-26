from types import SimpleNamespace

from app.db import SessionLocal
from app.models import (
    ApprovalGate,
    ReproductionAttempt,
    Repository,
    SandboxRun,
)
from app.workers.tasks import clone_and_index


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


def test_worker_persists_reproduction_attempt(monkeypatch):
    db = SessionLocal()

    try:
        repo = (
            db.query(Repository)
            .order_by(Repository.id)
            .first()
        )

        assert repo is not None

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
    )

    def fake_clone_and_read_sources_in_sandbox(
        clone_url,
        ref,
        token,
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
    ):
        return FakeResult()

    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        fake_clone_and_read_sources_in_sandbox,
    )

    monkeypatch.setattr(
        "app.workers.tasks.get_installation_token_sync",
        lambda installation_id: "test-token",
    )

    monkeypatch.setattr(
        "app.workers.tasks.run_reproduction_test",
        fake_run_reproduction_test,
    )

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

        assert run.status == "completed"

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