import re
import shlex

from e2b import Sandbox

from app.config import settings

COMMAND_TIMEOUT = 120
SANDBOX_TIMEOUT = 15 * 60
MAX_FILE_BYTES = 200_000
MAX_FILES = 200


def _sanitize_error(text: str, token: str) -> str:
    """
    Remove GitHub credentials from error messages before
    they can be stored in logs or the database.
    """

    if token:
        text = text.replace(token, "[REDACTED]")

    # Also protect GitHub token-looking values in case they
    # appear inside a generated clone URL.
    text = re.sub(
        r"ghs_[A-Za-z0-9_]+",
        "[REDACTED_GITHUB_TOKEN]",
        text,
    )

    # Protect the authenticated GitHub URL form.
    text = re.sub(
        r"https://x-access-token:[^@\s]+@github\.com/",
        "https://github.com/",
        text,
    )

    return text


def clone_and_read_sources(
    clone_url: str,
    ref: str,
    token: str,
) -> tuple[str, dict[str, str]]:

    kwargs: dict = {
        "timeout": SANDBOX_TIMEOUT
    }

    if settings.e2b_api_key:
        kwargs["api_key"] = settings.e2b_api_key

    sandbox = Sandbox.create(**kwargs)

    try:
        safe_ref = shlex.quote(ref)
        safe_token = shlex.quote(token)

        repository_path = clone_url.removeprefix(
            "https://github.com/"
        )

        clone_command = (
            "git clone --depth 1 "
            f"--branch {safe_ref} "
            f"https://x-access-token:{safe_token}@github.com/"
            f"{repository_path} "
            "/home/user/repo"
        )

        try:
            sandbox.commands.run(
                clone_command,
                timeout=COMMAND_TIMEOUT,
            )

        except Exception as exc:

            details = str(exc)

            for attr in (
                "stdout",
                "stderr",
                "exit_code",
            ):
                value = getattr(exc, attr, None)

                if value:
                    details += f"\n{attr}: {value}"

            details = _sanitize_error(
                details,
                token,
            )

            raise RuntimeError(
                f"E2B git clone failed:\n{details}"
            ) from exc

        listed = sandbox.commands.run(
            "cd /home/user/repo && "
            "git ls-files '*.py' '*.js' '*.ts' '*.tsx' '*.jsx'",
            timeout=COMMAND_TIMEOUT,
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

            content = sandbox.files.read(
                abs_path
            )

            if len(
                content.encode("utf-8")
            ) > MAX_FILE_BYTES:
                continue

            files[rel] = content

        return sandbox.sandbox_id, files

    finally:
        sandbox.kill()