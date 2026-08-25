import shlex

from e2b import Sandbox

from app.config import settings

COMMAND_TIMEOUT = 120
SANDBOX_TIMEOUT = 15 * 60
MAX_FILE_BYTES = 200_000
MAX_FILES = 200


def clone_and_read_sources(
    clone_url: str,
    ref: str,
    token: str,
) -> tuple[str, dict[str, str]]:
    kwargs: dict = {"timeout": SANDBOX_TIMEOUT}

    if settings.e2b_api_key:
        kwargs["api_key"] = settings.e2b_api_key

    sandbox = Sandbox.create(**kwargs)

    try:
        safe_ref = shlex.quote(ref)
        safe_clone_url = shlex.quote(clone_url)
        safe_token = shlex.quote(token)

        clone_command = (
            "git -c credential.helper='!f() { "
            "echo username=x-access-token; "
            f"echo password={safe_token}; "
            "}; f' "
            "clone --depth 1 "
            f"--branch {safe_ref} "
            f"{safe_clone_url} "
            "/home/user/repo"
        )

        sandbox.commands.run(
            clone_command,
            timeout=COMMAND_TIMEOUT,
        )

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
            content = sandbox.files.read(abs_path)

            if len(content.encode("utf-8")) > MAX_FILE_BYTES:
                continue

            files[rel] = content

        return sandbox.sandbox_id, files

    finally:
        sandbox.kill()