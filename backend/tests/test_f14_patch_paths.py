from types import SimpleNamespace

import pytest

from app.services.patch_apply import (
    PatchPathError,
    apply_diff_in_sandbox,
    parse_patch_paths,
    validate_patch_paths,
)
from app.services.patcher import generate_patch


ALLOWED = "app/services/math.py"


def _inplace(path: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        "+new\n"
    )


def _sandbox():
    return SimpleNamespace(
        files=SimpleNamespace(write=lambda path, content: None),
        write_file=lambda path, content: None,
    )


def test_accepts_single_file_inplace_diff():
    diff = _inplace(ALLOWED)
    validate_patch_paths(diff, ALLOWED)
    parsed = parse_patch_paths(diff)
    assert parsed.paths == frozenset({ALLOWED})
    assert parsed.is_new is False
    assert parsed.is_delete is False
    assert parsed.is_rename is False


def test_rejects_second_source_file():
    diff = _inplace(ALLOWED) + _inplace("app/services/other.py")
    with pytest.raises(PatchPathError, match="only"):
        validate_patch_paths(diff, ALLOWED)


def test_rejects_test_file():
    with pytest.raises(PatchPathError):
        validate_patch_paths(_inplace("tests/test_math.py"), ALLOWED)


def test_rejects_pytest_ini():
    with pytest.raises(PatchPathError):
        validate_patch_paths(_inplace("pytest.ini"), ALLOWED)


def test_rejects_conftest():
    with pytest.raises(PatchPathError):
        validate_patch_paths(_inplace("backend/tests/conftest.py"), ALLOWED)


def test_rejects_pyproject():
    with pytest.raises(PatchPathError):
        validate_patch_paths(_inplace("pyproject.toml"), ALLOWED)


def test_rejects_package_json():
    with pytest.raises(PatchPathError):
        validate_patch_paths(_inplace("package.json"), ALLOWED)


def test_rejects_ci_workflow():
    with pytest.raises(PatchPathError):
        validate_patch_paths(
            _inplace(".github/workflows/tests.yml"), ALLOWED
        )


def test_rejects_new_file():
    diff = (
        f"diff --git a/{ALLOWED} b/{ALLOWED}\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        f"+++ b/{ALLOWED}\n"
        "@@ -0,0 +1,1 @@\n"
        "+new\n"
    )
    with pytest.raises(PatchPathError, match="in-place"):
        validate_patch_paths(diff, ALLOWED)


def test_rejects_deleted_file():
    diff = (
        "diff --git a/app/unrelated.py b/app/unrelated.py\n"
        "deleted file mode 100644\n"
        "--- a/app/unrelated.py\n"
        "+++ /dev/null\n"
        "@@ -1,1 +0,0 @@\n"
        "-gone\n"
    )
    with pytest.raises(PatchPathError):
        validate_patch_paths(diff, ALLOWED)


def test_rejects_renamed_file():
    diff = (
        f"diff --git a/{ALLOWED} b/app/services/renamed.py\n"
        f"rename from {ALLOWED}\n"
        "rename to app/services/renamed.py\n"
        f"--- a/{ALLOWED}\n"
        "+++ b/app/services/renamed.py\n"
    )
    with pytest.raises(PatchPathError, match="in-place"):
        validate_patch_paths(diff, ALLOWED)


def test_rejects_path_traversal():
    diff = (
        "diff --git a/../secret.py b/../secret.py\n"
        "--- a/../secret.py\n"
        "+++ b/../secret.py\n"
    )
    with pytest.raises(PatchPathError, match="traversal"):
        validate_patch_paths(diff, ALLOWED)


def test_rejects_absolute_path():
    diff = (
        "diff --git a/tmp/x.py b/tmp/x.py\n"
        "--- a/tmp/x.py\n"
        "+++ /tmp/x.py\n"
    )
    with pytest.raises(PatchPathError, match="absolute"):
        validate_patch_paths(diff, ALLOWED)


def test_rejects_malformed_quoted_path():
    diff = (
        'diff --git "a/app/math.py" "b/app/math.py"\n'
        '--- "a/app/math.py"\n'
        '+++ "b/app/math.py"\n'
    )
    with pytest.raises(PatchPathError, match="unparseable"):
        validate_patch_paths(diff, ALLOWED)


def test_rejects_dev_null_create():
    diff = (
        "--- /dev/null\n"
        f"+++ b/{ALLOWED}\n"
        "@@ -0,0 +1,1 @@\n"
        "+new\n"
    )
    with pytest.raises(PatchPathError, match="in-place"):
        validate_patch_paths(diff, ALLOWED)


def test_rejects_multi_file_diff():
    diff = _inplace(ALLOWED) + "\n" + _inplace("package.json")
    with pytest.raises(PatchPathError):
        validate_patch_paths(diff, ALLOWED)


def test_apply_does_not_call_git_when_validation_fails(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("git apply must not run")

    monkeypatch.setattr("app.services.patch_apply.run_sandbox_command", boom)
    ok, err = apply_diff_in_sandbox(
        _sandbox(),
        _inplace("package.json"),
        allowed_path=ALLOWED,
    )
    assert ok is False
    assert "patch path validation failed" in err


def test_apply_does_not_write_diff_when_validation_fails():
    written = []

    sandbox = SimpleNamespace(
        write_file=lambda path, content: written.append(path),
        files=SimpleNamespace(write=lambda path, content: written.append(path)),
    )
    ok, err = apply_diff_in_sandbox(
        sandbox,
        _inplace("tests/test_math.py"),
        allowed_path=ALLOWED,
    )
    assert ok is False
    assert written == []
    assert "patch path validation failed" in err


def test_generate_patch_rejects_package_json_diff(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "test-key")

    def fake_completion(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=_inplace("package.json"))
                )
            ]
        )

    monkeypatch.setattr("litellm.completion", fake_completion)
    with pytest.raises(PatchPathError):
        generate_patch(
            path=ALLOWED,
            source="def calculate():\n    return 1 / 0\n",
            test_source="def test(): pass",
            stderr="ZeroDivisionError",
            exception_type="ZeroDivisionError",
        )


def test_generate_patch_rejects_test_file_diff(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "test-key")

    def fake_completion(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=_inplace("tests/test_math.py"))
                )
            ]
        )

    monkeypatch.setattr("litellm.completion", fake_completion)
    with pytest.raises(PatchPathError):
        generate_patch(
            path=ALLOWED,
            source="def calculate():\n    return 1 / 0\n",
            test_source="def test(): pass",
            stderr="ZeroDivisionError",
            exception_type="ZeroDivisionError",
        )


def test_generate_patch_accepts_matching_source_path(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    diff = _inplace(ALLOWED)

    def fake_completion(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=diff))
            ]
        )

    monkeypatch.setattr("litellm.completion", fake_completion)
    result = generate_patch(
        path=ALLOWED,
        source="def calculate():\n    return 1 / 0\n",
        test_source="def test(): pass",
        stderr="ZeroDivisionError",
        exception_type="ZeroDivisionError",
    )
    assert result.diff.startswith(f"diff --git a/{ALLOWED}")
