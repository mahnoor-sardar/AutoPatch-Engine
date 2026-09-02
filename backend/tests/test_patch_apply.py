from types import SimpleNamespace

from app.services.patch_apply import (
    apply_diff_in_sandbox,
    command_exit_code,
)


DIFF = "diff --git a/x b/x\n--- a/x\n+++ b/x\n"


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
    ok, err = apply_diff_in_sandbox(_sandbox(), DIFF)
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
    ok, err = apply_diff_in_sandbox(_sandbox(), DIFF)
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
    ok, err = apply_diff_in_sandbox(_sandbox(), DIFF)
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
    ok, err = apply_diff_in_sandbox(_sandbox(), DIFF)
    assert ok is False
    assert "git apply failed (exit 1)" in err
    assert "git apply died" in err


def test_empty_diff_is_not_applied(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("sandbox command must not run")

    monkeypatch.setattr("app.services.patch_apply.run_sandbox_command", boom)
    ok, err = apply_diff_in_sandbox(_sandbox(), "  \n")
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
    ok, err = apply_diff_in_sandbox(_sandbox(), DIFF)
    assert ok is False
    assert "super-secret-value" not in err
    assert "[REDACTED]" in err
