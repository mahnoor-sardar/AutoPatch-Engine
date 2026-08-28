import logging
from datetime import datetime, timezone

from app.config import settings
from app.db import SessionLocal
from app.models import (
    ApprovalGate,
    PatchAttempt,
    ReproductionAttempt,
    Repository,
    SandboxRun,
    Symbol,
)
from app.services import e2b_runner, indexer
from app.services.approval import (
    MERGE_GATE,
    PATCH_REVIEW_GATE,
    STAGE_CLONE,
    STAGE_MERGE,
    STAGE_PATCH_APPLY,
    STAGE_PATCH_REVIEW,
    STAGE_PR,
    create_pending_gate,
)
from app.services.audit import log_audit
from app.services.diagnostic import locate_frames
from app.services.embeddings import store_symbol_embeddings
from app.services.events import notify_run_event
from app.services.github_app import (
    clone_url,
    get_installation_token_sync,
)
from app.services.gemini import diagnose_reproduction
from app.services.github_pr import create_pull_request
from app.services.harness import run_full_test_suite, run_reproduction_test
from app.services.patcher import LlmNotConfigured, generate_patch
from app.services.repro import synthesize_repro
from app.services.stacktrace import parse_stack_trace
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
MAX_PATCH_ATTEMPTS = 5


def _load_run(db, run_id: int) -> SandboxRun:
    return db.query(SandboxRun).filter(SandboxRun.id == run_id).one()


def _require_gate(db, run: SandboxRun, name: str) -> ApprovalGate:
    gate = (
        db.query(ApprovalGate)
        .filter(ApprovalGate.run_id == run.id, ApprovalGate.gate == name)
        .order_by(ApprovalGate.id.desc())
        .first()
    )
    if gate is None or gate.status != "approved":
        raise RuntimeError(f"{name} requires Android approval")
    return gate


def _control_or_stop(db, run: SandboxRun) -> bool:
    db.refresh(run)
    if run.control_state == "killed":
        run.status = "killed"
        db.commit()
        return True
    if run.control_state == "paused":
        run.status = "paused"
        db.commit()
        return True
    return False


def _finish(run: SandboxRun, started, status: str, error: str | None = None):
    finished = datetime.now(timezone.utc)
    run.status = status
    run.error = error
    run.finished_at = finished
    run.duration_ms = int((finished - started).total_seconds() * 1000)


@celery_app.task(name="clone_and_index")
def clone_and_index(run_id: int) -> None:
    db = SessionLocal()
    run = _load_run(db, run_id)
    _require_gate(db, run, "sandbox_provision")

    if _control_or_stop(db, run):
        db.close()
        return

    started = datetime.now(timezone.utc)
    run.status = "running"
    run.started_at = started
    run.pipeline_stage = STAGE_CLONE
    db.commit()
    notify_run_event(db, run, "Sandbox running", f"{run.repo} clone started")

    sandbox = None
    try:
        repo = (
            db.query(Repository)
            .filter(Repository.full_name == run.repo)
            .one()
        )
        token = get_installation_token_sync(repo.installation_id)
        sandbox, files = e2b_runner.clone_and_read_sources_in_sandbox(
            clone_url=clone_url(run.repo),
            ref=run.ref,
            token=token,
        )
        run.e2b_sandbox_id = sandbox.sandbox_id
        db.commit()

        install_code, _install_out, install_err = (
            e2b_runner.install_project_dependencies(sandbox)
        )
        if install_code != 0:
            _finish(
                run,
                started,
                "failed",
                f"dependency install failed: {install_err[:500]}",
            )
            db.commit()
            notify_run_event(db, run, "Run failed", "dependency install failed")
            return

        if _control_or_stop(db, run):
            return

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
        store_symbol_embeddings(db, run.id)

        if run.stack_trace:
            parsed_trace = parse_stack_trace(run.stack_trace)
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
                parsed_trace.frames, symbols, sources=files
            )
            if locations:
                location = locations[-1]
                source = files.get(location.path)
                if source is None:
                    matching_paths = [
                        path
                        for path in files
                        if path.endswith(location.path)
                    ]
                    if len(matching_paths) == 1:
                        source = files[matching_paths[0]]
                if source is not None:
                    try:
                        reproduction = synthesize_repro(
                            location=location,
                            source=source,
                            exception_type=parsed_trace.exception_type,
                            message=parsed_trace.message,
                        )
                        result = run_reproduction_test(
                            sandbox=sandbox,
                            test_path=reproduction.test_path,
                            test_source=reproduction.test_source,
                            install_dependencies=False,
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

                        if result.reproduced:
                            try:
                                diagnosis = diagnose_reproduction(
                                    path=location.path,
                                    name=location.name,
                                    line=location.start_line,
                                    exception_type=parsed_trace.exception_type,
                                    source=source,
                                    test_source=reproduction.test_source,
                                    stderr=result.stderr,
                                    stack_trace=run.stack_trace,
                                )
                                log_audit(
                                    db,
                                    "diagnosis",
                                    run.id,
                                    None,
                                    diagnosis,
                                )
                            except Exception:
                                logger.exception("gemini diagnosis failed")

                            if settings.autopatch_stop_after_repro:
                                _finish(run, started, "completed")
                                db.commit()
                                notify_run_event(
                                    db,
                                    run,
                                    "Run completed",
                                    f"{run.repo} stopped after reproduction",
                                )
                                return
                            try:
                                diff = generate_patch(
                                    path=location.path,
                                    source=source,
                                    test_source=reproduction.test_source,
                                    stderr=result.stderr,
                                    exception_type=parsed_trace.exception_type,
                                )
                                run.patch_attempts = 1
                                run.current_diff = diff
                                run.pipeline_stage = STAGE_PATCH_REVIEW
                                db.add(
                                    PatchAttempt(
                                        run_id=run.id,
                                        attempt_number=1,
                                        diff=diff,
                                        status="pending_review",
                                    )
                                )
                                db.commit()
                                create_pending_gate(db, run, PATCH_REVIEW_GATE)
                                _finish(run, started, "awaiting_patch_review")
                                db.commit()
                                notify_run_event(
                                    db,
                                    run,
                                    "Patch ready for review",
                                    f"{run.repo} diff waiting on Android",
                                    {"has_diff": "true"},
                                )
                                return
                            except LlmNotConfigured as exc:
                                _finish(run, started, "failed", str(exc))
                                db.commit()
                                notify_run_event(
                                    db, run, "Run failed", str(exc)[:180]
                                )
                                return
                            except Exception:
                                logger.exception("patch generation failed")
                                _finish(
                                    run,
                                    started,
                                    "failed",
                                    "patch generation failed",
                                )
                                db.commit()
                                notify_run_event(
                                    db,
                                    run,
                                    "Run failed",
                                    "patch generation failed",
                                )
                                return
                    except ValueError as exc:
                        db.add(
                            ReproductionAttempt(
                                run_id=run.id,
                                stack_trace=run.stack_trace,
                                diagnostic_path=location.path,
                                diagnostic_name=location.name,
                                diagnostic_line=location.start_line,
                                reproduced=False,
                                stderr=str(exc),
                            )
                        )
                        db.commit()

        run.e2b_sandbox_id = sandbox.sandbox_id
        _finish(run, started, "completed")
        db.commit()
        notify_run_event(db, run, "Run completed", f"{run.repo} finished")
    except Exception as exc:
        db.rollback()
        run = _load_run(db, run_id)
        _finish(run, started, "failed", str(exc))
        db.commit()
        notify_run_event(db, run, "Run failed", str(exc)[:180])
        raise
    finally:
        if sandbox is not None:
            try:
                sandbox.kill()
            except Exception:
                logger.exception("failed to kill sandbox")
        db.close()


@celery_app.task(name="apply_patch_and_verify")
def apply_patch_and_verify(run_id: int) -> None:
    db = SessionLocal()
    run = _load_run(db, run_id)
    _require_gate(db, run, PATCH_REVIEW_GATE)
    if _control_or_stop(db, run):
        db.close()
        return
    if not run.current_diff:
        raise RuntimeError("no patch diff to apply")

    started = datetime.now(timezone.utc)
    run.status = "running"
    run.pipeline_stage = STAGE_PATCH_APPLY
    db.commit()
    sandbox = None
    try:
        repo = (
            db.query(Repository)
            .filter(Repository.full_name == run.repo)
            .one()
        )
        token = get_installation_token_sync(repo.installation_id)
        sandbox, files = e2b_runner.clone_and_read_sources_in_sandbox(
            clone_url=clone_url(run.repo),
            ref=run.ref,
            token=token,
        )
        run.e2b_sandbox_id = sandbox.sandbox_id
        db.commit()
        install_code, _out, install_err = e2b_runner.install_project_dependencies(
            sandbox
        )
        if install_code != 0:
            _finish(
                run,
                started,
                "failed",
                f"dependency install failed: {install_err[:500]}",
            )
            db.commit()
            return
        sandbox.files.write("/tmp/autopatch.diff", run.current_diff)
        try:
            sandbox.commands.run(
                "cd /home/user/repo && git apply /tmp/autopatch.diff",
                timeout=120,
            )
            apply_ok = True
            apply_err = ""
        except Exception as exc:
            apply_ok = False
            apply_err = str(exc)

        latest = (
            db.query(ReproductionAttempt)
            .filter(ReproductionAttempt.run_id == run.id)
            .order_by(ReproductionAttempt.id.desc())
            .first()
        )
        suite = None
        if apply_ok and latest and latest.test_path and latest.test_source:
            suite = run_reproduction_test(
                sandbox,
                latest.test_path,
                latest.test_source,
                install_dependencies=False,
            )
            if not suite.reproduced:
                full = run_full_test_suite(sandbox)
                tests_pass = full.exit_code == 0
            else:
                tests_pass = False
        else:
            tests_pass = False

        record = (
            db.query(PatchAttempt)
            .filter(PatchAttempt.run_id == run.id)
            .order_by(PatchAttempt.id.desc())
            .first()
        )
        if record:
            record.status = "applied" if tests_pass else "failed"
            record.stderr = apply_err or (suite.stderr if suite else None)
            db.commit()

        if tests_pass:
            run.pipeline_stage = STAGE_MERGE
            create_pending_gate(db, run, MERGE_GATE)
            _finish(run, started, "awaiting_merge")
            db.commit()
            notify_run_event(
                db, run, "Merge OTP required", f"{run.repo} is green"
            )
            return

        if run.patch_attempts >= MAX_PATCH_ATTEMPTS:
            _finish(run, started, "failed", "patch attempts exhausted")
            db.commit()
            return

        location_path = latest.diagnostic_path if latest else next(iter(files))
        source = files.get(location_path, "")
        try:
            diff = generate_patch(
                path=location_path,
                source=source,
                test_source=latest.test_source if latest else "",
                stderr=apply_err or (suite.stderr if suite else ""),
                exception_type=None,
                previous_error=apply_err,
            )
        except LlmNotConfigured:
            _finish(run, started, "failed", "LLM_API_KEY is not set")
            db.commit()
            return

        run.patch_attempts += 1
        run.current_diff = diff
        run.pipeline_stage = STAGE_PATCH_REVIEW
        db.add(
            PatchAttempt(
                run_id=run.id,
                attempt_number=run.patch_attempts,
                diff=diff,
                status="pending_review",
            )
        )
        db.commit()
        create_pending_gate(db, run, PATCH_REVIEW_GATE)
        _finish(run, started, "awaiting_patch_review")
        db.commit()
    except Exception as exc:
        db.rollback()
        run = _load_run(db, run_id)
        _finish(run, started, "failed", str(exc))
        db.commit()
        raise
    finally:
        if sandbox is not None:
            try:
                sandbox.kill()
            except Exception:
                logger.exception("failed to kill sandbox")
        db.close()


@celery_app.task(name="open_github_pr")
def open_github_pr(run_id: int) -> None:
    db = SessionLocal()
    run = _load_run(db, run_id)
    _require_gate(db, run, MERGE_GATE)
    if _control_or_stop(db, run):
        db.close()
        return
    started = datetime.now(timezone.utc)
    run.pipeline_stage = STAGE_PR
    sandbox = None
    try:
        repo = (
            db.query(Repository)
            .filter(Repository.full_name == run.repo)
            .one()
        )
        token = get_installation_token_sync(repo.installation_id)
        branch = f"autopatch/run-{run.id}"
        sandbox, _files = e2b_runner.clone_and_read_sources_in_sandbox(
            clone_url=clone_url(run.repo),
            ref=run.ref,
            token=token,
        )
        run.e2b_sandbox_id = sandbox.sandbox_id
        db.commit()
        if run.current_diff:
            sandbox.files.write("/tmp/autopatch.diff", run.current_diff)
            sandbox.commands.run(
                "cd /home/user/repo && git apply /tmp/autopatch.diff",
                timeout=120,
            )
        sandbox.commands.run(
            "cd /home/user/repo && "
            "git config user.email autopatch@local && "
            "git config user.name AutoPatch && "
            f"git checkout -b {branch} && "
            "git add -A && "
            "git commit -m 'fix: verified autopatch' && "
            f"git push origin {branch}",
            timeout=120,
        )
        pr = create_pull_request(
            token=token,
            repo=run.repo,
            title=f"AutoPatch: verified fix for run {run.id}",
            body="Verified reproduction and tests. Android merge OTP approved.",
            head=branch,
            base=run.ref or "main",
        )
        run.pr_url = pr.get("html_url")
        _finish(run, started, "completed")
        db.commit()
        log_audit(db, "pr_opened", run.id, None, run.pr_url)
        notify_run_event(db, run, "Pull request opened", run.pr_url or "")
    except Exception as exc:
        db.rollback()
        run = _load_run(db, run_id)
        _finish(run, started, "failed", str(exc))
        db.commit()
        raise
    finally:
        if sandbox is not None:
            try:
                sandbox.kill()
            except Exception:
                logger.exception("failed to kill sandbox")
        db.close()


@celery_app.task(name="expire_approval_gates")
def expire_approval_gates() -> int:
    from app.services.approval import expire_stale_gates

    db = SessionLocal()
    try:
        return len(expire_stale_gates(db))
    finally:
        db.close()
