import json
import logging
import re
import shlex

from e2b import Sandbox

from app.services.providers import (
    COMMAND_TIMEOUT,
    get_sandbox_provider,
    refresh_egress_allowlist,
    wrap_raw_sandbox,
)

MAX_FILE_BYTES = 200_000
MAX_FILES = 200

logger = logging.getLogger(__name__)


def _sanitize_error(text: str, token: str) -> str:
    if token:
        text = text.replace(token, "[REDACTED]")

    text = re.sub(
        r"ghs_[A-Za-z0-9_]+",
        "[REDACTED_GITHUB_TOKEN]",
        text,
    )
    text = re.sub(
        r"https://x-access-token:[^@\s]+@github\.com/",
        "https://github.com/",
        text,
    )
    return text


def _run(sandbox, command: str, timeout: int):
    if hasattr(sandbox, "commands"):
        return sandbox.commands.run(command, timeout=timeout)
    return sandbox.run(command, timeout=timeout)


def _read(sandbox, path: str) -> str:
    if hasattr(sandbox, "read_file"):
        return sandbox.read_file(path)
    return sandbox.files.read(path)


def _session(sandbox):
    if hasattr(sandbox, "run"):
        return sandbox
    return wrap_raw_sandbox(sandbox)


def create_sandbox() -> Sandbox:
    session = get_sandbox_provider().create()
    return session.raw


def clone_and_read_sources(
    sandbox: Sandbox,
    clone_url: str,
    ref: str,
    token: str,
) -> dict[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", ref):
        raise ValueError("invalid git ref")

    safe_ref = shlex.quote(ref)
    safe_token = shlex.quote(token)
    repository_path = clone_url.removeprefix("https://github.com/")

    clone_command = (
        "git clone --depth 1 "
        f"--branch {safe_ref} "
        f"https://x-access-token:{safe_token}@github.com/"
        f"{repository_path} "
        "/home/user/repo"
    )

    try:
        _run(sandbox, clone_command, COMMAND_TIMEOUT)
    except Exception as exc:
        details = str(exc)
        for attr in ("stdout", "stderr", "exit_code"):
            value = getattr(exc, attr, None)
            if value:
                details += f"\n{attr}: {value}"
        details = _sanitize_error(details, token)
        raise RuntimeError(f"E2B git clone failed:\n{details}") from exc

    listed = _run(
        sandbox,
        "cd /home/user/repo && "
        "git ls-files '*.py' '*.js' '*.ts' '*.tsx' '*.jsx'",
        COMMAND_TIMEOUT,
    )

    paths = [
        p.strip()
        for p in listed.stdout.splitlines()
        if p.strip()
    ][:MAX_FILES]

    files: dict[str, str] = {}
    for rel in paths:
        if "node_modules/" in rel:
            continue
        abs_path = f"/home/user/repo/{rel}"
        content = _read(sandbox, abs_path)
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            continue
        files[rel] = content

    return files


def clone_and_read_sources_in_sandbox(
    clone_url: str,
    ref: str,
    token: str,
):
    session = get_sandbox_provider().create()
    try:
        refresh_egress_allowlist(session)
        files = clone_and_read_sources(
            sandbox=session,
            clone_url=clone_url,
            ref=ref,
            token=token,
        )
        return session, files
    except Exception:
        session.kill()
        raise


def path_exists(sandbox, path: str) -> bool:
    result = _run(
        sandbox,
        f"test -e {shlex.quote(path)}; echo $?",
        30,
    )
    return (result.stdout or "").strip().endswith("0")


def install_project_dependencies(sandbox: Sandbox) -> tuple[int, str, str]:
    root = "/home/user/repo"
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    try:
        refresh_egress_allowlist(_session(sandbox))
        if path_exists(sandbox, f"{root}/pyproject.toml"):
            result = _run(
                sandbox,
                f"cd {root} && python -m pip install -e .",
                COMMAND_TIMEOUT,
            )
        elif path_exists(sandbox, f"{root}/requirements.txt"):
            result = _run(
                sandbox,
                f"cd {root} && python -m pip install -r requirements.txt",
                COMMAND_TIMEOUT,
            )
        elif path_exists(sandbox, f"{root}/backend/requirements.txt"):
            result = _run(
                sandbox,
                f"cd {root}/backend && python -m pip install -r requirements.txt",
                COMMAND_TIMEOUT,
            )
        else:
            result = None

        if result is not None:
            stdout_parts.append(result.stdout or "")
            stderr_parts.append(result.stderr or "")

        if path_exists(sandbox, f"{root}/package.json"):
            npm = _run(
                sandbox,
                f"cd {root} && npm install",
                COMMAND_TIMEOUT,
            )
            stdout_parts.append(npm.stdout or "")
            stderr_parts.append(npm.stderr or "")

        return 0, "".join(stdout_parts), "".join(stderr_parts)
    except Exception as exc:
        return (
            int(getattr(exc, "exit_code", 1) or 1),
            getattr(exc, "stdout", "") or "",
            getattr(exc, "stderr", "") or str(exc),
        )
