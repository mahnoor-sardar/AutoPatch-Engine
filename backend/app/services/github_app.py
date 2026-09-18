import hashlib
import hmac
import time
from pathlib import Path

import httpx
import jwt

from app.config import ROOT, settings


def verify_webhook_signature(
    body: bytes,
    secret: str,
    header: str | None,
) -> bool:
    if not header or not secret:
        return False

    digest = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    expected = f"sha256={digest}"

    return hmac.compare_digest(expected, header)


def _private_key() -> str:
    path = settings.github_app_private_key_path

    if not path:
        raise RuntimeError("GITHUB_APP_PRIVATE_KEY_PATH is not set")

    key_path = Path(path)

    if not key_path.is_absolute():
        key_path = ROOT / path

    return key_path.read_text(encoding="utf-8")


def make_app_jwt() -> str:
    if not settings.github_app_id:
        raise RuntimeError("GITHUB_APP_ID is not set")

    now = int(time.time())

    payload = {
        "iat": now - 60,
        "exp": now + 540,
        "iss": settings.github_app_id,
    }

    return jwt.encode(
        payload,
        _private_key(),
        algorithm="RS256",
    )


PERMISSIONS_REPO_READ = {"contents": "read"}
PERMISSIONS_PR_WRITE = {"contents": "write", "pull_requests": "write"}

_TOKEN_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def _repository_name(owner_repo: str) -> str:
    parts = (owner_repo or "").strip().strip("/").split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError("repository scope is required")
    return parts[1]


def _scoped_token_payload(
    permissions: dict[str, str] | None,
    repositories: list[str] | None,
) -> dict:
    if not permissions:
        raise ValueError("installation token permissions are required")
    if not repositories:
        raise ValueError("installation token repository scope is required")
    names = [name.strip() for name in repositories if str(name).strip()]
    if not names:
        raise ValueError("installation token repository scope is required")
    return {
        "permissions": dict(permissions),
        "repositories": names,
    }


def _installation_access_tokens_url(installation_id: int) -> str:
    return (
        "https://api.github.com"
        f"/app/installations/{installation_id}/access_tokens"
    )


async def get_installation_token(installation_id: int) -> str:
    token = make_app_jwt()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            _installation_access_tokens_url(installation_id),
            headers={
                "Authorization": f"Bearer {token}",
                **_TOKEN_HEADERS,
            },
        )
    response.raise_for_status()
    return response.json()["token"]


def get_installation_token_sync(
    installation_id: int,
    *,
    permissions: dict[str, str],
    repositories: list[str],
) -> str:
    payload = _scoped_token_payload(permissions, repositories)
    app_jwt = make_app_jwt()
    with httpx.Client(timeout=30) as client:
        response = client.post(
            _installation_access_tokens_url(installation_id),
            headers={
                "Authorization": f"Bearer {app_jwt}",
                **_TOKEN_HEADERS,
            },
            json=payload,
        )
    response.raise_for_status()
    return response.json()["token"]


def installation_token_for_repo(
    installation_id: int,
    owner_repo: str,
    permissions: dict[str, str],
) -> str:
    """Mint a repo-scoped installation token. Never omits permissions or scope."""
    return get_installation_token_sync(
        installation_id,
        permissions=permissions,
        repositories=[_repository_name(owner_repo)],
    )


def clone_url(owner_repo: str) -> str:
    return f"https://github.com/{owner_repo}.git"
