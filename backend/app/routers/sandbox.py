from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.db import get_db
from app.models import Repository, SandboxRun
from app.schemas import SandboxRunCreate
from app.workers.tasks import clone_and_index

router = APIRouter()


@router.post("/v1/sandbox/runs", dependencies=[Depends(require_api_key)])
def create_run(body: SandboxRunCreate, db: Session = Depends(get_db)):
    repo = db.query(Repository).filter(Repository.full_name == body.repo).one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="repository not registered via GitHub App")
    run = SandboxRun(status="queued", repo=body.repo, ref=body.ref)
    db.add(run)
    db.commit()
    db.refresh(run)
    clone_and_index.delay(run.id)
    return {"id": run.id, "status": run.status}


@router.get("/v1/sandbox/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
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
