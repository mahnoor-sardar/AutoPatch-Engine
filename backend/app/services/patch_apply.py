from pathlib import Path


REPO_ROOT = "/home/user/repo"


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
