from pathlib import Path

from app.services.e2b_runner import (
    COMMAND_TIMEOUT,
    run_sandbox_command,
    sanitize_log_text,
)


REPO_ROOT = "/home/user/repo"
DIFF_PATH = "/tmp/autopatch.diff"
_APPLY_OUTPUT_LIMIT = 4000


def patch_target_paths(diff: str) -> list[str]:
    seen: list[str] = []
    for line in (diff or "").splitlines():
        if not line.startswith("+++ "):
            continue
        rest = line[4:].split("\t", 1)[0].strip()
        if rest in {"/dev/null", "dev/null"}:
            continue
        if rest.startswith("b/"):
            rest = rest[2:]
        if not rest or rest.startswith("/") or ".." in Path(rest).parts:
            continue
        if rest not in seen:
            seen.append(rest)
    return seen


def ensure_eof_newline_on_patch_targets(repo_root: str | Path, diff: str) -> list[str]:
    root = Path(repo_root).resolve()
    changed: list[str] = []
    for rel in patch_target_paths(diff):
        path = (root / rel).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if not path.is_file():
            continue
        data = path.read_bytes()
        if not data or data.endswith(b"\n") or b"\0" in data:
            continue
        path.write_bytes(data + b"\n")
        changed.append(rel.replace("\\", "/"))
    return changed


def normalize_sandbox_patch_targets(
    sandbox,
    diff: str,
    repo_root: str = REPO_ROOT,
) -> None:
    files_api = getattr(sandbox, "files", None)
    for rel in patch_target_paths(diff):
        abs_path = f"{repo_root.rstrip('/')}/{rel}"
        try:
            if hasattr(sandbox, "read_file"):
                content = sandbox.read_file(abs_path)
            elif files_api is not None:
                content = files_api.read(abs_path)
            else:
                continue
        except Exception:
            continue
        if not isinstance(content, str):
            continue
        if not content or content.endswith("\n") or "\0" in content:
            continue
        try:
            if hasattr(sandbox, "write_file"):
                sandbox.write_file(abs_path, content + "\n")
            elif files_api is not None:
                files_api.write(abs_path, content + "\n")
        except Exception:
            continue


def command_exit_code(result) -> int:
    return int(getattr(result, "exit_code", 0) or 0)


def _clip_apply_output(text: str) -> str:
    text = sanitize_log_text(text or "")
    if len(text) <= _APPLY_OUTPUT_LIMIT:
        return text
    return text[:_APPLY_OUTPUT_LIMIT] + "\n...[truncated]"


def _write_sandbox_diff(sandbox, diff: str) -> None:
    files_api = getattr(sandbox, "files", None)
    if hasattr(sandbox, "write_file"):
        sandbox.write_file(DIFF_PATH, diff)
        return
    if files_api is not None:
        files_api.write(DIFF_PATH, diff)
        return
    raise RuntimeError("sandbox cannot write patch diff")


def _git_apply_error(label: str, result=None, exc: BaseException | None = None) -> str:
    if exc is not None:
        code = int(getattr(exc, "exit_code", 1) or 1)
        stderr = getattr(exc, "stderr", "") or ""
        stdout = getattr(exc, "stdout", "") or ""
        detail = _clip_apply_output(stderr or stdout or str(exc))
        suffix = f" (exit {code})"
        if detail:
            return f"{label}{suffix}: {detail}"
        return f"{label}{suffix}"
    code = command_exit_code(result)
    stderr = _clip_apply_output(getattr(result, "stderr", "") or "")
    stdout = _clip_apply_output(getattr(result, "stdout", "") or "")
    detail = stderr or stdout
    suffix = f" (exit {code})"
    if detail:
        return f"{label}{suffix}: {detail}"
    return f"{label}{suffix}"


def apply_diff_in_sandbox(sandbox, diff: str) -> tuple[bool, str]:
    """Normalize targets, `git apply --check`, then `git apply`."""
    if not (diff or "").strip():
        return False, "no patch diff to apply"
    _write_sandbox_diff(sandbox, diff)
    normalize_sandbox_patch_targets(sandbox, diff)
    check_cmd = f"cd {REPO_ROOT} && git apply --check {DIFF_PATH}"
    apply_cmd = f"cd {REPO_ROOT} && git apply {DIFF_PATH}"
    try:
        checked = run_sandbox_command(sandbox, check_cmd, COMMAND_TIMEOUT)
    except Exception as exc:
        return False, _git_apply_error("git apply --check failed", exc=exc)
    if command_exit_code(checked) != 0:
        return False, _git_apply_error("git apply --check failed", result=checked)
    try:
        applied = run_sandbox_command(sandbox, apply_cmd, COMMAND_TIMEOUT)
    except Exception as exc:
        return False, _git_apply_error("git apply failed", exc=exc)
    if command_exit_code(applied) != 0:
        return False, _git_apply_error("git apply failed", result=applied)
    return True, ""
