from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.services.e2b_runner import (
    COMMAND_TIMEOUT,
    run_sandbox_command,
    sanitize_log_text,
)


REPO_ROOT = "/home/user/repo"
DIFF_PATH = "/tmp/autopatch.diff"
_APPLY_OUTPUT_LIMIT = 4000
_NULL_PATHS = frozenset({"/dev/null", "dev/null"})


class PatchPathError(ValueError):
    """Unified diff is not a single in-place edit of the allowed source path."""


@dataclass(frozen=True)
class PatchPathSet:
    paths: frozenset[str]
    is_new: bool = False
    is_delete: bool = False
    is_rename: bool = False


def normalize_repo_path(raw: str) -> str:
    text = (raw or "").replace("\\", "/").strip()
    if not text:
        raise PatchPathError("patch path validation failed: empty path")
    lowered = text.lower()
    if lowered.startswith("file:"):
        raise PatchPathError("patch path validation failed: absolute path")
    if text.startswith("//") or text.startswith("\\\\"):
        raise PatchPathError("patch path validation failed: absolute path")
    if text.startswith("/") or text.startswith("~"):
        raise PatchPathError("patch path validation failed: absolute path")
    first = text.split("/", 1)[0]
    if len(first) >= 2 and first[1] == ":":
        raise PatchPathError("patch path validation failed: absolute path")
    parts: list[str] = []
    for part in PurePosixPath(text).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            raise PatchPathError("patch path validation failed: path traversal")
        parts.append(part)
    if not parts:
        raise PatchPathError("patch path validation failed: empty path")
    return "/".join(parts)


def _is_null_path(raw: str) -> bool:
    text = (raw or "").replace("\\", "/").strip()
    if text.startswith("a/") or text.startswith("b/"):
        text = text[2:]
    return text in _NULL_PATHS or text.endswith("/dev/null")


def _strip_ab_prefix(raw: str) -> str:
    text = (raw or "").replace("\\", "/").strip()
    if text.startswith("a/") or text.startswith("b/"):
        return text[2:]
    return text


def _unquoted_path_token(raw: str) -> str:
    text = (raw or "").split("\t", 1)[0].strip()
    if not text:
        raise PatchPathError("patch path validation failed: empty path")
    if '"' in text or "'" in text:
        raise PatchPathError("patch path validation failed: unparseable path")
    return text


def _parse_diff_git_paths(line: str) -> tuple[str, str]:
    rest = line[len("diff --git ") :]
    rest = _unquoted_path_token(rest)
    if not rest.startswith("a/"):
        raise PatchPathError("patch path validation failed: unparseable path")
    marker = " b/"
    index = rest.find(marker)
    if index == -1:
        raise PatchPathError("patch path validation failed: unparseable path")
    left = rest[2:index]
    right = rest[index + len(marker) :]
    if not left or not right:
        raise PatchPathError("patch path validation failed: empty path")
    return normalize_repo_path(left), normalize_repo_path(right)


def _parse_file_header_path(line: str) -> str | None:
    rest = _unquoted_path_token(line[4:])
    if _is_null_path(rest):
        return None
    return normalize_repo_path(_strip_ab_prefix(rest))


def parse_patch_paths(diff: str) -> PatchPathSet:
    """Return every repository path a unified diff would change. Fail closed."""
    if not (diff or "").strip():
        raise PatchPathError("patch path validation failed: empty diff")

    paths: set[str] = set()
    is_new = False
    is_delete = False
    is_rename = False
    saw_header = False

    for line in diff.splitlines():
        if line.startswith("diff --git "):
            saw_header = True
            left, right = _parse_diff_git_paths(line)
            if left != right:
                is_rename = True
            paths.add(left)
            paths.add(right)
            continue
        if line.startswith("rename from "):
            saw_header = True
            is_rename = True
            paths.add(normalize_repo_path(_unquoted_path_token(line[12:])))
            continue
        if line.startswith("rename to "):
            saw_header = True
            is_rename = True
            paths.add(normalize_repo_path(_unquoted_path_token(line[10:])))
            continue
        if line.startswith("copy from ") or line.startswith("copy to "):
            saw_header = True
            is_rename = True
            token = line.split(" ", 2)[-1]
            paths.add(normalize_repo_path(_unquoted_path_token(token)))
            continue
        if line.startswith("new file mode "):
            is_new = True
            continue
        if line.startswith("deleted file mode "):
            is_delete = True
            continue
        if line.startswith("--- "):
            saw_header = True
            parsed = _parse_file_header_path(line)
            if parsed is None:
                is_new = True
            else:
                paths.add(parsed)
            continue
        if line.startswith("+++ "):
            saw_header = True
            parsed = _parse_file_header_path(line)
            if parsed is None:
                is_delete = True
            else:
                paths.add(parsed)
            continue

    if not saw_header or not paths:
        raise PatchPathError("patch path validation failed: unparseable path")
    return PatchPathSet(
        paths=frozenset(paths),
        is_new=is_new,
        is_delete=is_delete,
        is_rename=is_rename,
    )


def patch_target_paths(diff: str) -> list[str]:
    return sorted(parse_patch_paths(diff).paths)


def validate_patch_paths(diff: str, allowed_path: str) -> None:
    allowed = normalize_repo_path(allowed_path)
    parsed = parse_patch_paths(diff)
    if parsed.is_new or parsed.is_delete or parsed.is_rename:
        raise PatchPathError(
            "patch path validation failed: patch must be an in-place edit of a single file"
        )
    if parsed.paths != frozenset({allowed}):
        raise PatchPathError(
            "patch path validation failed: patch must modify only "
            f"{allowed}"
        )


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


def apply_diff_in_sandbox(
    sandbox, diff: str, *, allowed_path: str
) -> tuple[bool, str]:
    """Validate paths, `git apply --check`, then `git apply` the approved diff."""
    if not (diff or "").strip():
        return False, "no patch diff to apply"
    if not (allowed_path or "").strip():
        return False, "localized source path is required"
    try:
        validate_patch_paths(diff, allowed_path)
    except ValueError as exc:
        return False, str(exc)
    _write_sandbox_diff(sandbox, diff)
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
