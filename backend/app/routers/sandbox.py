from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.db import get_db
from app.models import Repository, SandboxRun
from app.schemas import SandboxRunCreate
from app.workers.tasks import clone_and_index

router = APIRouter()


@router.post(
    "/v1/sandbox/runs",
    dependencies=[Depends(require_api_key)],
)
def create_run(
    body: SandboxRunCreate,
    db: Session = Depends(get_db),
):
    repo = (
        db.query(Repository)
        .filter(Repository.full_name == body.repo)
        .one_or_none()
    )

    if repo is None:
        raise HTTPException(
            status_code=404,
            detail="repository not registered via GitHub App",
        )

    run = SandboxRun(
        status="queued",
        repo=body.repo,
        ref=body.ref,
    )

    db.add(run)
    db.commit()
    db.refresh(run)

    clone_and_index.delay(run.id)

    return {
        "id": run.id,
        "status": run.status,
    }


@router.get(
    "/v1/sandbox/runs/{run_id}",
    dependencies=[Depends(require_api_key)],
)
def get_run(
    run_id: int,
    db: Session = Depends(get_db),
):
    run = (
        db.query(SandboxRun)
        .filter(SandboxRun.id == run_id)
        .one_or_none()
    )

    if run is None:
        raise HTTPException(
            status_code=404,
            detail="run not found",
        )

    return {
        "id": run.id,
        "status": run.status,
        "repo": run.repo,
        "ref": run.ref,
        "e2b_sandbox_id": run.e2b_sandbox_id,
        "duration_ms": run.duration_ms,
        "error": run.error,
        "symbol_count": len(run.symbols),
    }


@router.get(
    "/v1/sandbox/runs",
    dependencies=[Depends(require_api_key)],
)
def list_runs(
    limit: int = 20,
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 100))

    runs = (
        db.query(SandboxRun)
        .order_by(SandboxRun.id.desc())
        .limit(limit)
        .all()
    )

    total = (
        db.query(func.count(SandboxRun.id))
        .scalar()
        or 0
    )

    successful = (
        db.query(func.count(SandboxRun.id))
        .filter(SandboxRun.status == "completed")
        .scalar()
        or 0
    )

    running = (
        db.query(func.count(SandboxRun.id))
        .filter(
            SandboxRun.status.in_(["running", "queued"])
        )
        .scalar()
        or 0
    )

    failed = (
        db.query(func.count(SandboxRun.id))
        .filter(SandboxRun.status == "failed")
        .scalar()
        or 0
    )

    return {
        "stats": {
            "total": total,
            "successful": successful,
            "running": running,
            "failed": failed,
        },
        "runs": [
            {
                "id": run.id,
                "repo": run.repo,
                "ref": run.ref,
                "status": run.status,
                "duration_ms": run.duration_ms,
                "error": run.error,
                "started_at": (
                    run.started_at.isoformat()
                    if run.started_at
                    else None
                ),
                "finished_at": (
                    run.finished_at.isoformat()
                    if run.finished_at
                    else None
                ),
                "symbol_count": len(run.symbols),
            }
            for run in runs
        ],
    }