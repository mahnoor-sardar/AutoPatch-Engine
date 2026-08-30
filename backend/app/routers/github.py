import json
import httpx

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from app.auth import require_api_key
from app.config import settings
from app.db import get_db
from app.models import GitHubInstallation, Repository, SandboxRun
from app.services.approval import create_pending_provision_gate
from app.services.github_app import get_installation_token, verify_webhook_signature

router = APIRouter()

def _upsert_repos(db: Session, installation_id: int, repos: list[dict]) -> None:
    rows = []

    for repo in repos:
        full_name = repo.get("full_name")

        if not full_name:
            continue

        rows.append(
            {
                "full_name": full_name,
                "installation_id": installation_id,
                "default_branch": repo.get("default_branch") or "main",
            }
        )

    if not rows:
        return

    stmt = insert(Repository).values(rows)

    stmt = stmt.on_conflict_do_update(
        index_elements=[Repository.full_name],
        set_={
            "installation_id": stmt.excluded.installation_id,
            "default_branch": stmt.excluded.default_branch,
        },
    )

    db.execute(stmt)


@router.post("/v1/github/webhook")
async def github_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
):
    body = await request.body()

    if not verify_webhook_signature(
        body,
        settings.github_webhook_secret,
        x_hub_signature_256,
    ):
        raise HTTPException(status_code=401, detail="invalid signature")

    payload = json.loads(body or b"{}")
    event = x_github_event or ""
    print("GITHUB EVENT:", event)

    if event == "ping":
        return {"ok": True, "event": "ping"}

    if event == "installation":
        installation = payload.get("installation") or {}
        installation_id = installation.get("id")
        account = (installation.get("account") or {}).get("login") or ""

        if installation_id:
            row = (
                db.query(GitHubInstallation)
                .filter(
                    GitHubInstallation.installation_id == installation_id
                )
                .one_or_none()
            )

            if row is None:
                db.add(
                    GitHubInstallation(
                        installation_id=installation_id,
                        account_login=account,
                    )
                )
            else:
                row.account_login = account

            _upsert_repos(
                db,
                installation_id,
                payload.get("repositories") or [],
            )

            db.commit()

        return {"ok": True, "event": event}

    if event == "installation_repositories":
        installation_id = (
            payload.get("installation") or {}
        ).get("id")

        if installation_id:
            _upsert_repos(
                db,
                installation_id,
                payload.get("repositories_added") or [],
            )

            for repo in payload.get("repositories_removed") or []:
                full_name = repo.get("full_name")

                if full_name:
                    (
                        db.query(Repository)
                        .filter(Repository.full_name == full_name)
                        .delete()
                    )

            db.commit()

        return {"ok": True, "event": event}

    if event == "push":
        repository = payload.get("repository") or {}
        repo_full_name = repository.get("full_name")

        ref = payload.get("ref") or ""

        if ref.startswith("refs/heads/"):
            ref = ref.removeprefix("refs/heads/")

        if not repo_full_name:
            return {
                "ok": True,
                "event": event,
                "ignored": True,
            }

        repo = (
            db.query(Repository)
            .filter(Repository.full_name == repo_full_name)
            .one_or_none()
        )

        if repo is None:
            return {
                "ok": True,
                "event": event,
                "ignored": True,
                "reason": "repository_not_installed",
            }

        run = SandboxRun(
            status="queued",
            repo=repo_full_name,
            ref=ref or repo.default_branch,
        )

        db.add(run)
        db.commit()
        db.refresh(run)

        gate = create_pending_provision_gate(db, run)

        return {
            "ok": True,
            "event": event,
            "run_id": run.id,
            "gate": gate.gate,
            "gate_status": gate.status,
            "repo": repo_full_name,
            "ref": ref or repo.default_branch,
        }

    return {
        "ok": True,
        "event": event,
        "ignored": True,
    }


@router.get(
    "/v1/github/repos",
    dependencies=[Depends(require_api_key)],
)
async def github_repositories(installation_id: int):
    token = await get_installation_token(installation_id)

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            "https://api.github.com/installation/repositories",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    response.raise_for_status()

    data = response.json()

    return {
        "repositories": [
            {
                "full_name": repo["full_name"],
                "default_branch": repo.get("default_branch") or "main",
                "private": repo.get("private", False),
                "html_url": repo.get("html_url"),
            }
            for repo in data.get("repositories", [])
        ]
    }


@router.get(
    "/v1/github/connected",
    dependencies=[Depends(require_api_key)],
)
def connected_repositories(db: Session = Depends(get_db)):
    rows = db.query(Repository).order_by(Repository.full_name).all()
    return {
        "repositories": [
            {
                "full_name": row.full_name,
                "default_branch": row.default_branch,
                "installation_id": row.installation_id,
            }
            for row in rows
        ]
    }
