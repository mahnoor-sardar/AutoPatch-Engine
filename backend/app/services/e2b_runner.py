from contextlib import contextmanager
from contextvars import ContextVar
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

_agent_log_run_id: ContextVar[int | None] = ContextVar("agent_log_run_id", default=None)
_agent_log_token: ContextVar[str] = ContextVar("agent_log_token", default="")

_BEARER_HEADER = re.compile(
    r"(?i)(\bAuthorization\s*:\s*Bearer\s+)(\S+)"
)
_SECRET_ASSIGN = re.compile(
    r"(?i)("
    r"[\"'](?:api[_-]?key|access[_-]?token|secret|password|authorization)[\"']"
    r"|"
    r"(?:api[_-]?key|access[_-]?token|secret|password)"
    r")"
    r"(\s*[=:]\s*)"
    r"([\"']?)"
    r"([^\s\"',}\\]+)"
)


def sanitize_log_text(text: str, token: str = "") -> str:
    if not text:
        return ""
    if token:
        text = text.replace(token, "[REDACTED]")
    text = re.sub(r"ghs_[A-Za-z0-9_]+", "[REDACTED_GITHUB_TOKEN]", text)
    text = re.sub(r"ghp_[A-Za-z0-9]+", "[REDACTED_GITHUB_TOKEN]", text)
    text = re.sub(r"github_pat_[A-Za-z0-9_]+", "[REDACTED_GITHUB_TOKEN]", text)
    text = re.sub(
        r"https://x-access-token:[^@\s]+@github\.com/",
        "https://github.com/",
        text,
    )
    text = _BEARER_HEADER.sub(r"\1[REDACTED]", text)
    text = _SECRET_ASSIGN.sub(r"\1\2\3[REDACTED]", text)
    return text


def _sanitize_error(text: str, token: str) -> str:
    return sanitize_log_text(text, token)


@contextmanager
def agent_log_scope(run_id: int, token: str = ""):
    rid = _agent_log_run_id.set(run_id)
    tok = _agent_log_token.set(token or "")
    try:
        yield
    finally:
        from app.services.events import flush_agent_logs

        try:
            flush_agent_logs(run_id, token or "")
        finally:
            _agent_log_run_id.reset(rid)
            _agent_log_token.reset(tok)


def _emit_agent_log(stream: str, chunk: str) -> None:
    run_id = _agent_log_run_id.get()
    if run_id is None or not chunk:
        return
    from app.services.events import publish_agent_log

    publish_agent_log(run_id, stream, chunk, token=_agent_log_token.get() or "")


def _run(sandbox, command: str, timeout: int, on_stdout=None, on_stderr=None):
    streamed = False

    def _stdout(data):
        nonlocal streamed
        streamed = True
        text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
        if on_stdout:
            on_stdout(text)
        _emit_agent_log("stdout", text)

    def _stderr(data):
        nonlocal streamed
        streamed = True
        text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
        if on_stderr:
            on_stderr(text)
        _emit_agent_log("stderr", text)

    if hasattr(sandbox, "commands") and sandbox.commands is not None:
        runner = sandbox.commands.run
    elif hasattr(sandbox, "run"):
        runner = sandbox.run
    else:
        raise AttributeError("sandbox has no command runner")
    try:
        result = runner(
            command,
            timeout=timeout,
            on_stdout=_stdout,
            on_stderr=_stderr,
        )
    except TypeError:
        result = runner(command, timeout=timeout)
        streamed = False
    if not streamed:
        _emit_agent_log("stdout", getattr(result, "stdout", None) or "")
        _emit_agent_log("stderr", getattr(result, "stderr", None) or "")
    return result


def run_sandbox_command(sandbox, command: str, timeout: int, on_stdout=None, on_stderr=None):
    return _run(sandbox, command, timeout, on_stdout=on_stdout, on_stderr=on_stderr)


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


_CLONE_URL = re.compile(
    r"^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+\.git$"
)
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_ZERO_SHA = "0" * 40


def parse_git_sha(value: str | None) -> str:
    sha = (value or "").strip().lower()
    if not _GIT_SHA.fullmatch(sha) or sha == _ZERO_SHA:
        raise ValueError("invalid git sha")
    return sha


def checkout_head_sha(sandbox) -> str:
    result = _run(sandbox, "git -C /home/user/repo rev-parse HEAD", 30)
    return parse_git_sha((getattr(result, "stdout", None) or "").strip())


def commit_parent_sha(sandbox) -> str:
    result = _run(sandbox, "git -C /home/user/repo rev-parse HEAD^", 30)
    return parse_git_sha((getattr(result, "stdout", None) or "").strip())


def _git_bearer_header_opt(token: str) -> str:
    if not token or "\n" in token or "\r" in token:
        raise ValueError("invalid github token")
    return "-c http.extraHeader=" + shlex.quote(f"Authorization: Bearer {token}")


def _assert_tokenless_origin(origin: str, expected_url: str, token: str) -> None:
    value = (origin or "").strip()
    lowered = value.lower()
    if (
        value != expected_url
        or "x-access-token" in lowered
        or "authorization" in lowered
        or "ghs_" in value
        or "ghp_" in value
        or "github_pat_" in value
        or (token and token in value)
    ):
        raise RuntimeError("git remote origin must not contain credentials")


def clone_and_read_sources(
    sandbox: Sandbox,
    clone_url: str,
    ref: str,
    token: str,
    sha: str | None = None,
) -> dict[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", ref):
        raise ValueError("invalid git ref")
    if not _CLONE_URL.fullmatch(clone_url):
        raise ValueError("invalid clone url")

    pinned_sha = parse_git_sha(sha) if sha else None
    safe_ref = shlex.quote(ref)
    safe_url = shlex.quote(clone_url)
    header_opt = _git_bearer_header_opt(token)
    if pinned_sha:
        safe_sha = shlex.quote(pinned_sha)
        clone_commands = [
            f"git init /home/user/repo",
            "git -C /home/user/repo remote add origin " + safe_url,
            (
                f"git -C /home/user/repo {header_opt} fetch --depth 1 "
                f"origin {safe_sha}"
            ),
            f"git -C /home/user/repo checkout --detach {safe_sha}",
        ]
    else:
        clone_commands = [
            (
                f"git {header_opt} clone --depth 1 "
                f"--branch {safe_ref} {safe_url} /home/user/repo"
            )
        ]

    try:
        for command in clone_commands:
            _run(sandbox, command, COMMAND_TIMEOUT)
        _run(
            sandbox,
            "git -C /home/user/repo remote set-url origin " + safe_url,
            30,
        )
        origin = _run(
            sandbox,
            "git -C /home/user/repo config --get remote.origin.url",
            30,
        )
        _assert_tokenless_origin(
            getattr(origin, "stdout", None) or "",
            clone_url,
            token,
        )
        if pinned_sha:
            head = checkout_head_sha(sandbox)
            if head != pinned_sha:
                raise RuntimeError(
                    f"checkout HEAD {head} does not match source_sha {pinned_sha}"
                )
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
    sha: str | None = None,
    on_created=None,
):
    session = get_sandbox_provider().create()
    try:
        if on_created is not None and on_created(session) is False:
            return session, None
        refresh_egress_allowlist(session)
        files = clone_and_read_sources(
            sandbox=session,
            clone_url=clone_url,
            ref=ref,
            token=token,
            sha=sha,
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


def push_branch(sandbox, branch: str, token: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch):
        raise ValueError("invalid git branch")
    header_opt = _git_bearer_header_opt(token)
    safe_branch = shlex.quote(branch)
    _run(
        sandbox,
        "cd /home/user/repo && "
        f"git {header_opt} push origin {safe_branch}",
        COMMAND_TIMEOUT,
    )
