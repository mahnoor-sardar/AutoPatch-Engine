from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.db import get_db
from app.models import ApprovalGate, Repository, SandboxRun
from app.schemas import ApprovalRequest, SandboxRunCreate
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

    gate = ApprovalGate(
        run_id=run.id,
        gate="sandbox_provision",
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=90),
    )

    db.add(gate)
    db.commit()

    return {
        "id": run.id,
        "status": run.status,
    }


@router.post(
    "/v1/sandbox/runs/{run_id}/approval",
    dependencies=[Depends(require_api_key)],
)
def approve_sandbox(
    run_id: int,
    body: ApprovalRequest,
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

    gate = (
        db.query(ApprovalGate)
        .filter(
            ApprovalGate.run_id == run.id,
            ApprovalGate.gate == "sandbox_provision",
        )
        .one_or_none()
    )

    if gate is None:
        raise HTTPException(
            status_code=404,
            detail="approval gate not found",
        )

    if (
        gate.expires_at is not None
        and gate.expires_at <= datetime.now(timezone.utc)
    ):
        gate.status = "expired"
        db.commit()

        raise HTTPException(
            status_code=409,
            detail="approval gate has expired",
        )

    if gate.status != "pending":
        raise HTTPException(
            status_code=409,
            detail="approval gate is not pending",
        )

    gate.status = "approved"
    gate.device_id = body.device_id
    gate.approved_at = datetime.now(timezone.utc)

    db.commit()

    clone_and_index.delay(run.id)

    return {
        "ok": True,
        "run_id": run.id,
        "gate": gate.gate,
        "status": gate.status,
    }


@router.get(
    "/v1/sandbox/approvals/pending",
    dependencies=[Depends(require_api_key)],
)
def list_pending_approvals(
    device_id: str,
    db: Session = Depends(get_db),
):
    gates = (
        db.query(ApprovalGate, SandboxRun)
        .join(SandboxRun, ApprovalGate.run_id == SandboxRun.id)
        .filter(
            ApprovalGate.gate == "sandbox_provision",
            ApprovalGate.status == "pending",
            ApprovalGate.expires_at > datetime.now(timezone.utc),
        )
        .order_by(ApprovalGate.id.desc())
        .all()
    )

    return {
        "approvals": [
            {
                "run_id": run.id,
                "repository": run.repo,
                "gate": gate.gate,
                "expires_at": (
                    gate.expires_at.isoformat()
                    if gate.expires_at
                    else None
                ),
            }
            for gate, run in gates
            if gate.device_id is None or gate.device_id == device_id
        ]
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

    stats = (
        db.query(
            func.count(SandboxRun.id).label("total"),
            func.count(SandboxRun.id)
            .filter(SandboxRun.status == "completed")
            .label("successful"),
            func.count(SandboxRun.id)
            .filter(
                SandboxRun.status.in_(["running", "queued"])
            )
            .label("running"),
            func.count(SandboxRun.id)
            .filter(SandboxRun.status == "failed")
            .label("failed"),
        )
        .one()
    )

    total = stats.total or 0
    successful = stats.successful or 0
    running = stats.running or 0
    failed = stats.failed or 0

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