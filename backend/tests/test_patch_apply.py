from types import SimpleNamespace

from app.services.patch_apply import (
    DIFF_PATH,
    REPO_ROOT,
    apply_diff_in_sandbox,
    command_exit_code,
)


DIFF = "diff --git a/x b/x\n--- a/x\n+++ b/x\n"
TARGET = f"{REPO_ROOT}/x"
ORIGINAL = "hello"


class RecordingSandbox:
    def __init__(self, source=ORIGINAL):
        self.store = {TARGET: source}
        self.writes = []
        self.files = SimpleNamespace(write=self.write_file, read=self.read_file)

    def write_file(self, path, content):
        self.writes.append(path)
        self.store[path] = content

    def read_file(self, path):
        return self.store[path]


def _sandbox():
    return SimpleNamespace(
        files=SimpleNamespace(write=lambda path, content: None),
        write_file=lambda path, content: None,
    )


def test_command_exit_code_defaults_missing_to_zero():
    assert command_exit_code(SimpleNamespace(stdout="ok")) == 0
    assert command_exit_code(SimpleNamespace(exit_code=0)) == 0
    assert command_exit_code(SimpleNamespace(exit_code=1)) == 1
    assert command_exit_code(SimpleNamespace(exit_code=None)) == 0


def test_apply_runs_check_before_git_apply(monkeypatch):
    ran = []

    def fake_run(sandbox, command, timeout):
        ran.append(command)
        return SimpleNamespace(exit_code=0, stdout="", stderr="")

    monkeypatch.setattr("app.services.patch_apply.run_sandbox_command", fake_run)
    ok, err = apply_diff_in_sandbox(_sandbox(), DIFF, allowed_path="x")
    assert ok is True
    assert err == ""
    assert len(ran) == 2
    assert "git apply --check /tmp/autopatch.diff" in ran[0]
    assert "--check" not in ran[1]
    assert "git apply /tmp/autopatch.diff" in ran[1]


def test_failed_check_skips_apply(monkeypatch):
    ran = []

    def fake_run(sandbox, command, timeout):
        ran.append(command)
        return SimpleNamespace(
            exit_code=1,
            stdout="",
            stderr="error: corrupt patch",
        )

    monkeypatch.setattr("app.services.patch_apply.run_sandbox_command", fake_run)
    ok, err = apply_diff_in_sandbox(_sandbox(), DIFF, allowed_path="x")
    assert ok is False
    assert len(ran) == 1
    assert "--check" in ran[0]
    assert "git apply --check failed (exit 1)" in err
    assert "corrupt patch" in err


def test_apply_nonzero_exit_without_exception(monkeypatch):
    def fake_run(sandbox, command, timeout):
        if "--check" in command:
            return SimpleNamespace(exit_code=0, stdout="", stderr="")
        return SimpleNamespace(exit_code=2, stdout="", stderr="does not apply")

    monkeypatch.setattr("app.services.patch_apply.run_sandbox_command", fake_run)
    ok, err = apply_diff_in_sandbox(_sandbox(), DIFF, allowed_path="x")
    assert ok is False
    assert "git apply failed (exit 2)" in err
    assert "does not apply" in err


def test_apply_exception_is_failure(monkeypatch):
    class ApplyFailed(Exception):
        exit_code = 1
        stderr = "fatal: git apply died"
        stdout = ""

    def fake_run(sandbox, command, timeout):
        if "--check" in command:
            return SimpleNamespace(exit_code=0, stdout="", stderr="")
        raise ApplyFailed()

    monkeypatch.setattr("app.services.patch_apply.run_sandbox_command", fake_run)
    ok, err = apply_diff_in_sandbox(_sandbox(), DIFF, allowed_path="x")
    assert ok is False
    assert "git apply failed (exit 1)" in err
    assert "git apply died" in err


def test_empty_diff_is_not_applied(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("sandbox command must not run")

    monkeypatch.setattr("app.services.patch_apply.run_sandbox_command", boom)
    ok, err = apply_diff_in_sandbox(_sandbox(), "  \n", allowed_path="x")
    assert ok is False
    assert err == "no patch diff to apply"


def test_apply_error_sanitizes_secrets(monkeypatch):
    def fake_run(sandbox, command, timeout):
        return SimpleNamespace(
            exit_code=1,
            stdout="",
            stderr="api_key=super-secret-value",
        )

    monkeypatch.setattr("app.services.patch_apply.run_sandbox_command", fake_run)
    ok, err = apply_diff_in_sandbox(_sandbox(), DIFF, allowed_path="x")
    assert ok is False
    assert "super-secret-value" not in err
    assert "[REDACTED]" in err


def test_failed_check_does_not_mutate_source_without_eof_newline(monkeypatch):
    ran = []
    sandbox = RecordingSandbox()

    def fake_run(box, command, timeout):
        ran.append(command)
        return SimpleNamespace(
            exit_code=1,
            stdout="",
            stderr="error: corrupt patch",
        )

    def boom(*args, **kwargs):
        raise AssertionError("normalize_sandbox_patch_targets must not run")

    monkeypatch.setattr("app.services.patch_apply.run_sandbox_command", fake_run)
    monkeypatch.setattr(
        "app.services.patch_apply.normalize_sandbox_patch_targets",
        boom,
    )
    before = sandbox.store[TARGET]
    ok, err = apply_diff_in_sandbox(sandbox, DIFF, allowed_path="x")
    assert ok is False
    assert "--check" in ran[0]
    assert len(ran) == 1
    assert "git apply --check failed" in err
    assert sandbox.store[TARGET] == before == ORIGINAL
    assert not ORIGINAL.endswith("\n")
    assert sandbox.writes == [DIFF_PATH]


def test_failed_apply_after_successful_check_does_not_mutate_source(monkeypatch):
    sandbox = RecordingSandbox()

    def fake_run(box, command, timeout):
        if "--check" in command:
            return SimpleNamespace(exit_code=0, stdout="", stderr="")
        return SimpleNamespace(exit_code=2, stdout="", stderr="does not apply")

    monkeypatch.setattr("app.services.patch_apply.run_sandbox_command", fake_run)
    before = sandbox.store[TARGET]
    ok, err = apply_diff_in_sandbox(sandbox, DIFF, allowed_path="x")
    assert ok is False
    assert "git apply failed" in err
    assert sandbox.store[TARGET] == before == ORIGINAL
    assert sandbox.writes == [DIFF_PATH]


def test_apply_does_not_call_normalize_sandbox_patch_targets(monkeypatch):
    called = []

    def fake_run(sandbox, command, timeout):
        return SimpleNamespace(exit_code=0, stdout="", stderr="")

    def track(*args, **kwargs):
        called.append(True)

    monkeypatch.setattr("app.services.patch_apply.run_sandbox_command", fake_run)
    monkeypatch.setattr(
        "app.services.patch_apply.normalize_sandbox_patch_targets",
        track,
    )
    ok, err = apply_diff_in_sandbox(RecordingSandbox(), DIFF, allowed_path="x")
    assert ok is True
    assert err == ""
    assert called == []
