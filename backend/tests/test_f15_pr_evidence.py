from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.db import SessionLocal
from app.models import ApprovalGate, PatchAttempt, SandboxRun
from app.services.github_pr import (
    build_pr_body,
    patch_sha256,
    validate_reproduction_test_path,
)
from app.services.harness import ADDITIONAL_TESTS_SKIPPED
from app.workers.tasks import open_github_pr
from tests.test_patch_pipeline import (
    SEEDED_DIFF,
    TEST_SOURCE_SHA,
    _approve,
    _seed_run,
    _seed_verified_pr_records,
)

OLD_PR_BODY = "Verified reproduction and tests. Android merge OTP approved."
TEST_PATH = "tests/autopatch_repro_test.py"
TEST_SOURCE = "def test_repro(): pass\n"
DIAGNOSTIC_PATH = "backend/app/services/math.py"


class _Result:
    def __init__(self, stdout=""):
        self.stdout = stdout
        self.stderr = ""
        self.exit_code = 0


class OrderSandbox:
    sandbox_id = "sbx-f15"

    def __init__(self, events):
        self.events = events
        self.written = []
        self.files = SimpleNamespace(write=self.write_file)
        self.commands = SimpleNamespace(run=self._run)

    def write_file(self, path, content):
        self.events.append(("write", path, content))
        self.written.append((path, content))

    def _run(self, command, timeout=None, on_stdout=None, on_stderr=None):
        self.events.append(("cmd", command))
        return _Result(TEST_SOURCE_SHA + "\n")

    def kill(self):
        return None


def _seed_pr_run():
    run_id, repo = _seed_run(
        status="awaiting_merge",
        current_diff=SEEDED_DIFF,
        pipeline_stage="merge",
        source_sha=TEST_SOURCE_SHA,
        ref="main",
        patch_attempts=1,
    )
    _approve(run_id, "merge")
    db = SessionLocal()
    try:
        gate = (
            db.query(ApprovalGate)
            .filter(ApprovalGate.run_id == run_id, ApprovalGate.gate == "merge")
            .one()
        )
        gate.approved_at = datetime(2026, 9, 20, 9, 30, tzinfo=timezone.utc)
        db.commit()
    finally:
        db.close()
    _seed_verified_pr_records(
        run_id,
        diagnostic_path=DIAGNOSTIC_PATH,
        test_path=TEST_PATH,
        test_source=TEST_SOURCE,
        patch_stdout=ADDITIONAL_TESTS_SKIPPED,
        current_diff=SEEDED_DIFF,
    )
    return run_id, repo


def _stub_pr_flow(monkeypatch, *, sandbox=None, apply_impl=None):
    events = []
    pushed = []
    prs = []
    applies = []
    sandbox = sandbox or OrderSandbox(events)

    def apply_diff(sbx, diff, *, allowed_path):
        events.append(("apply", allowed_path, diff))
        applies.append({"allowed_path": allowed_path, "diff": diff})
        if apply_impl is not None:
            return apply_impl(sbx, diff, allowed_path=allowed_path)
        return True, None

    monkeypatch.setattr(
        "app.workers.tasks.installation_token_for_repo",
        lambda *a, **k: "ghs_token",
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        lambda **kwargs: (sandbox, {}),
    )
    monkeypatch.setattr("app.workers.tasks.apply_diff_in_sandbox", apply_diff)
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.checkout_head_sha",
        lambda sbx: TEST_SOURCE_SHA,
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.run_sandbox_command",
        lambda sbx, command, timeout: events.append(("git", command)),
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.commit_parent_sha",
        lambda sbx: TEST_SOURCE_SHA,
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.push_branch",
        lambda sbx, branch, token: pushed.append((branch, token)),
    )
    monkeypatch.setattr(
        "app.workers.tasks.create_pull_request",
        lambda **kwargs: prs.append(kwargs) or {"html_url": "https://github.com/a/b/pull/1"},
    )
    monkeypatch.setattr("app.services.fcm.send_push", lambda *a, **k: "ok")
    return events, pushed, prs, applies, sandbox


def test_open_github_pr_preserves_reproduction_test(monkeypatch):
    run_id, _repo = _seed_pr_run()
    events, pushed, prs, _applies, sandbox = _stub_pr_flow(monkeypatch)
    open_github_pr.run(run_id)
    kinds = [item[0] for item in events]
    assert kinds.index("apply") < kinds.index("write")
    assert kinds.index("write") < kinds.index("git")
    expected_path = f"/home/user/repo/{TEST_PATH}"
    assert sandbox.written == [(expected_path, TEST_SOURCE)]
    git_commands = [item[1] for item in events if item[0] == "git"]
    assert git_commands
    assert "git add -A" in git_commands[0]
    assert pushed
    assert prs


def test_open_github_pr_body_contains_verification_evidence(monkeypatch):
    run_id, repo = _seed_pr_run()
    _events, _pushed, prs, _applies, _sandbox = _stub_pr_flow(monkeypatch)
    open_github_pr.run(run_id)
    body = prs[0]["body"]
    assert body != OLD_PR_BODY
    assert OLD_PR_BODY not in body
    assert f"- Run ID: {run_id}" in body
    assert f"- Repository: {repo}" in body
    assert f"- Source SHA: {TEST_SOURCE_SHA}" in body
    assert f"- Diagnostic path: {DIAGNOSTIC_PATH}" in body
    assert f"- Reproduction test: {TEST_PATH}" in body
    assert "- Reproduction result: reproduced" in body
    assert "- Reproduction exit code: 1" in body
    assert "- Patch status: applied" in body
    assert "- Additional suite: skipped" in body
    assert "- Approval device: test-device" in body
    assert patch_sha256(SEEDED_DIFF) in body
    assert TEST_PATH in body
    assert "included in this PR" in body
    db = SessionLocal()
    try:
        patch = (
            db.query(PatchAttempt)
            .filter(PatchAttempt.run_id == run_id)
            .order_by(PatchAttempt.id.desc())
            .first()
        )
        patch_id = patch.id
    finally:
        db.close()
    assert f"- Patch attempt: {patch_id}" in body
    assert "2026-09-20T09:30:00+00:00" in body


def test_build_pr_body_does_not_invent_counts_or_old_sentence():
    body = build_pr_body(
        run_id=7,
        repo="owner/repo",
        ref="main",
        source_sha=TEST_SOURCE_SHA,
        diagnostic_path=DIAGNOSTIC_PATH,
        test_path=TEST_PATH,
        reproduced=True,
        reproduction_exit_code=1,
        patch_attempt_id=3,
        patch_status="applied",
        patch_stdout=None,
        current_diff=SEEDED_DIFF,
        merge_approved_at=None,
        approval_device_id="dev-1",
    )
    assert OLD_PR_BODY not in body
    assert "1 passed" not in body
    assert "all tests passed" not in body.lower()
    assert "- Additional suite: ran" in body
    assert "- Merge approval: not recorded" in body


@pytest.mark.parametrize(
    "seed",
    ["missing", "blank_path", "blank_source"],
)
def test_open_github_pr_fails_when_reproduction_test_missing(monkeypatch, seed):
    run_id, _repo = _seed_run(
        status="awaiting_merge",
        current_diff=SEEDED_DIFF,
        pipeline_stage="merge",
        source_sha=TEST_SOURCE_SHA,
    )
    _approve(run_id, "merge")
    if seed != "missing":
        _seed_verified_pr_records(
            run_id,
            test_path="" if seed == "blank_path" else TEST_PATH,
            test_source="" if seed == "blank_source" else TEST_SOURCE,
        )
    events, pushed, prs, applies, _sandbox = _stub_pr_flow(monkeypatch)
    open_github_pr.run(run_id)
    assert pushed == []
    assert prs == []
    assert applies == []
    assert "write" not in [item[0] for item in events]
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.status == "failed"
        assert "verified reproduction test is missing" in (run.error or "")
        assert run.pr_url is None
    finally:
        db.close()


def test_open_github_pr_preserves_f14_path_binding(monkeypatch):
    run_id, _repo = _seed_pr_run()
    _events, _pushed, prs, applies, _sandbox = _stub_pr_flow(monkeypatch)
    open_github_pr.run(run_id)
    assert applies
    assert applies[0]["allowed_path"] == DIAGNOSTIC_PATH
    assert applies[0]["allowed_path"] != TEST_PATH
    assert applies[0]["diff"] == SEEDED_DIFF
    assert prs


@pytest.mark.parametrize(
    "test_path",
    [
        "tests/autopatch_repro_test.py",
        "tests/autopatch_repro.test.ts",
        "tests/autopatch_repro.test.mjs",
    ],
)
def test_validate_reproduction_test_path_accepts_generated_paths(test_path):
    assert validate_reproduction_test_path(test_path) == test_path


@pytest.mark.parametrize(
    "test_path",
    [
        "../evil.py",
        "..\\evil.py",
        "/tmp/evil.py",
        "C:\\Windows\\evil.py",
    ],
)
def test_open_github_pr_rejects_unsafe_reproduction_test_path(monkeypatch, test_path):
    run_id, _repo = _seed_run(
        status="awaiting_merge",
        current_diff=SEEDED_DIFF,
        pipeline_stage="merge",
        source_sha=TEST_SOURCE_SHA,
    )
    _approve(run_id, "merge")
    _seed_verified_pr_records(run_id, test_path=test_path)
    events, pushed, prs, _applies, sandbox = _stub_pr_flow(monkeypatch)
    open_github_pr.run(run_id)
    assert sandbox.written == []
    assert "write" not in [item[0] for item in events]
    assert "git" not in [item[0] for item in events]
    assert pushed == []
    assert prs == []
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.status == "failed"
        assert "invalid reproduction test path" in (run.error or "")
        assert run.pr_url is None
    finally:
        db.close()
