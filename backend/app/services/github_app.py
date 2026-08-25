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


async def get_installation_token(installation_id: int) -> str:
    token = make_app_jwt()

    url = (
        "https://api.github.com"
        f"/app/installations/{installation_id}/access_tokens"
    )

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    response.raise_for_status()

    return response.json()["token"]


def clone_url(owner_repo: str) -> str:
    return f"https://github.com/{owner_repo}.git"
