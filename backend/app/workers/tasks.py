from datetime import datetime, timezone

from app.db import SessionLocal
from app.models import (
    ApprovalGate,
    ReproductionAttempt,
    Repository,
    SandboxRun,
    Symbol,
)
from app.services import e2b_runner, indexer
from app.services.diagnostic import locate_frames
from app.services.github_app import (
    clone_url,
    get_installation_token_sync,
)
from app.services.harness import run_reproduction_test
from app.services.repro import synthesize_python_repro
from app.services.stacktrace import parse_stack_trace
from app.workers.celery_app import celery_app


@celery_app.task(name="clone_and_index")
def clone_and_index(run_id: int) -> None:
    db = SessionLocal()

    run = (
        db.query(SandboxRun)
        .filter(SandboxRun.id == run_id)
        .one()
    )

    gate = (
        db.query(ApprovalGate)
        .filter(
            ApprovalGate.run_id == run.id,
            ApprovalGate.gate == "sandbox_provision",
        )
        .one_or_none()
    )

    if gate is None or gate.status != "approved":
        db.close()
        raise RuntimeError(
            "sandbox provisioning requires Android approval"
        )

    started = datetime.now(timezone.utc)

    run.status = "running"
    run.started_at = started
    db.commit()

    sandbox = None

    try:
        repo = (
            db.query(Repository)
            .filter(
                Repository.full_name == run.repo
            )
            .one()
        )

        token = get_installation_token_sync(
            repo.installation_id
        )

        url = clone_url(run.repo)

        sandbox, files = (
            e2b_runner.clone_and_read_sources_in_sandbox(
                clone_url=url,
                ref=run.ref,
                token=token,
            )
        )

        # ---------------------------------------------------------
        # Phase 2: index repository symbols
        # ---------------------------------------------------------

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

        db.commit()

        # ---------------------------------------------------------
        # Phase 3–4:
        # stack trace
        #     ↓
        # diagnostic location
        #     ↓
        # reproduction test
        #     ↓
        # E2B execution
        # ---------------------------------------------------------

        if run.stack_trace:

            parsed_trace = parse_stack_trace(
                run.stack_trace
            )

            symbols = [
                {
                    "path": path,
                    "name": name,
                    "kind": kind,
                    "start_line": line,
                }
                for path, name, kind, line in rows
            ]

            locations = locate_frames(
                parsed_trace.frames,
                symbols,
            )

            if locations:

                # The final frame is normally the deepest
                # application frame and therefore the best
                # diagnostic target.
                location = locations[-1]

                source = files.get(
                    location.path
                )

                # Support stack-trace paths that omit
                # the repository root prefix.
                if source is None:
                    matching_paths = [
                        path
                        for path in files
                        if path.endswith(
                            location.path
                        )
                    ]

                    if len(matching_paths) == 1:
                        source = files[
                            matching_paths[0]
                        ]

                if source is not None:

                    try:
                        reproduction = (
                            synthesize_python_repro(
                                location=location,
                                source=source,
                                exception_type=(
                                    parsed_trace.exception_type
                                ),
                                message=(
                                    parsed_trace.message
                                ),
                            )
                        )

                        result = run_reproduction_test(
                            sandbox=sandbox,
                            test_path=reproduction.test_path,
                            test_source=reproduction.test_source,
                        )

                        attempt = ReproductionAttempt(
                            run_id=run.id,
                            stack_trace=run.stack_trace,
                            diagnostic_path=location.path,
                            diagnostic_name=location.name,
                            diagnostic_line=location.start_line,
                            test_path=reproduction.test_path,
                            test_source=reproduction.test_source,
                            exit_code=result.exit_code,
                            stdout=result.stdout,
                            stderr=result.stderr,
                            reproduced=result.reproduced,
                        )

                        db.add(attempt)
                        db.commit()

                    except ValueError as exc:
                        attempt = ReproductionAttempt(
                            run_id=run.id,
                            stack_trace=run.stack_trace,
                            diagnostic_path=location.path,
                            diagnostic_name=location.name,
                            diagnostic_line=location.start_line,
                            reproduced=False,
                            stderr=str(exc),
                        )

                        db.add(attempt)
                        db.commit()

        finished = datetime.now(timezone.utc)

        run.e2b_sandbox_id = sandbox.sandbox_id
        run.status = "completed"
        run.finished_at = finished
        run.duration_ms = int(
            (
                finished - started
            ).total_seconds()
            * 1000
        )

        db.commit()

    except Exception as exc:

        finished = datetime.now(timezone.utc)

        db.rollback()

        run = (
            db.query(SandboxRun)
            .filter(
                SandboxRun.id == run_id
            )
            .one()
        )

        run.status = "failed"
        run.error = str(exc)
        run.finished_at = finished
        run.duration_ms = int(
            (
                finished - started
            ).total_seconds()
            * 1000
        )

        db.commit()

        raise

    finally:

        if sandbox is not None:
            try:
                sandbox.kill()
            except Exception:
                pass

        db.close()