from datetime import datetime, timezone

from app.db import SessionLocal
from app.models import Repository, SandboxRun, Symbol
from app.services import e2b_runner, indexer
from app.services.github_app import (
    clone_url,
    get_installation_token_sync,
)
from app.workers.celery_app import celery_app


@celery_app.task(name="clone_and_index")
def clone_and_index(run_id: int) -> None:
    db = SessionLocal()

    run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()

    started = datetime.now(timezone.utc)

    run.status = "running"
    run.started_at = started
    db.commit()

    try:
        repo = (
            db.query(Repository)
            .filter(Repository.full_name == run.repo)
            .one()
        )

        token = get_installation_token_sync(
            repo.installation_id
        )
        url = clone_url(run.repo)

        sandbox_id, files = e2b_runner.clone_and_read_sources(
            url,
            run.ref,
            token,
        )

        rows = indexer.index_files(files)

        db.bulk_insert_mappings(
            Symbol,
            [
                {
                    "run_id": run.id,
                    "path": path,
                    "name": name,
                    "kind": kind,
                    "start_line": line,
                }
                for path, name, kind, line in rows
            ],
        )

        finished = datetime.now(timezone.utc)

        run.e2b_sandbox_id = sandbox_id
        run.status = "completed"
        run.finished_at = finished
        run.duration_ms = int(
            (finished - started).total_seconds() * 1000
        )

        db.commit()

    except Exception as exc:
        finished = datetime.now(timezone.utc)

        # Roll back any failed transaction before updating
        # the run to its failed state.
        db.rollback()

        run = (
            db.query(SandboxRun)
            .filter(SandboxRun.id == run_id)
            .one()
        )

        run.status = "failed"
        run.error = str(exc)
        run.finished_at = finished
        run.duration_ms = int(
            (finished - started).total_seconds() * 1000
        )

        db.commit()

        raise

    finally:
        db.close()