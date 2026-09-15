import logging
from contextlib import ExitStack
from datetime import datetime, timezone

from celery.exceptions import MaxRetriesExceededError, Retry

from app.config import settings
from app.db import SessionLocal
from app.models import (
    ApprovalGate,
    AuditEvent,
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
    STAGE_PROVISION,
    create_pending_gate,
)
from app.services.audit import (
    ACTOR_WORKER,
    RESULT_SUCCESS,
    log_audit,
)
from app.services.diagnostic import locate_frames
from app.services.embeddings import store_symbol_embeddings
from app.services.events import notify_run_event
from app.services.github_app import (
    clone_url,
    get_installation_token_sync,
)
from app.services.gemini import diagnose_reproduction
from app.services.github_pr import create_pull_request
from app.services.harness import (
    ADDITIONAL_TESTS_SKIPPED,
    extra_suite_merge_message,
    extra_suite_ok,
    run_full_test_suite,
    run_reproduction_test,
)
from app.services.patcher import (
    LlmNotConfigured,
    LlmRequestTimeout,
    LlmTokenBudgetExceeded,
    PatchGenerationResult,
    diffs_are_identical,
    generate_patch,
)
from app.services.patch_apply import apply_diff_in_sandbox
from app.services.repro import synthesize_repro
from app.services.stacktrace import parse_stack_trace
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
MAX_PATCH_ATTEMPTS = 5
VERIFY_OUTPUT_LIMIT = 8000
IDENTICAL_PATCH_ERROR = "identical patch rejected"
EMPTY_PATCH_ERROR = "empty patch rejected"

TERMINAL_STATUSES = frozenset({"completed", "failed", "rejected", "killed"})
WAITING_STATUSES = frozenset(
    {"queued", "paused", "awaiting_patch_review", "awaiting_merge"}
)
PROTECTED_STATUSES = TERMINAL_STATUSES | WAITING_STATUSES
STAGE_RANK = {
    STAGE_PROVISION: 0,
    STAGE_CLONE: 1,
    STAGE_PATCH_REVIEW: 2,
    STAGE_PATCH_APPLY: 3,
    STAGE_MERGE: 4,
    STAGE_PR: 5,
}


def run_state_is_valid(run: SandboxRun) -> bool:
    if run.status == "running" and run.finished_at is not None:
        return False
    if run.status in TERMINAL_STATUSES and run.finished_at is None:
        return False
    return True


def _stage_rank(stage: str | None) -> int:
    return STAGE_RANK.get(stage or STAGE_PROVISION, 0)


def _load_run(db, run_id: int) -> SandboxRun:
    return db.query(SandboxRun).filter(SandboxRun.id == run_id).one()


def _lock_run(db, run: SandboxRun) -> SandboxRun:
    query = db.query(SandboxRun).filter(SandboxRun.id == run.id)
    if hasattr(query, "with_for_update"):
        query = query.with_for_update()
    return query.one()


def _mark_running(run: SandboxRun, stage: str, started) -> None:
    run.status = "running"
    run.pipeline_stage = stage
    run.started_at = started
    run.finished_at = None
    run.duration_ms = None


def _ensure_finished_at(run: SandboxRun, started=None) -> None:
    if run.finished_at is not None:
        return
    finished = datetime.now(timezone.utc)
    run.finished_at = finished
    start = started or run.started_at
    if start is None:
        return
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    run.duration_ms = int((finished - start).total_seconds() * 1000)


def _repair_stale_clone(run: SandboxRun) -> None:
    if run.current_diff:
        run.status = "awaiting_patch_review"
        run.pipeline_stage = STAGE_PATCH_REVIEW
    else:
        run.status = "completed"
        run.pipeline_stage = STAGE_CLONE
    _ensure_finished_at(run)


def _latest_patch_attempt(db, run: SandboxRun) -> PatchAttempt | None:
    return (
        db.query(PatchAttempt)
        .filter(PatchAttempt.run_id == run.id)
        .order_by(PatchAttempt.id.desc())
        .first()
    )


def _latest_diagnosis_text(db, run: SandboxRun) -> str | None:
    event = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.run_id == run.id,
            AuditEvent.action == "diagnosis",
        )
        .order_by(AuditEvent.id.desc())
        .first()
    )
    if event is None:
        return None
    detail = event.detail
    return detail if isinstance(detail, str) and detail.strip() else None


def _repair_stale_apply(db, run: SandboxRun) -> None:
    record = _latest_patch_attempt(db, run)
    if record is not None and record.status == "applied":
        run.status = "awaiting_merge"
        run.pipeline_stage = STAGE_MERGE
    elif run.patch_attempts >= MAX_PATCH_ATTEMPTS:
        run.status = "failed"
        if not run.error:
            run.error = "patch attempts exhausted"
    else:
        run.status = "awaiting_patch_review"
        run.pipeline_stage = STAGE_PATCH_REVIEW
    _ensure_finished_at(run)


def _claim_clone_stage(db, run: SandboxRun, started) -> bool:
    run = _lock_run(db, run)
    if run.status in TERMINAL_STATUSES:
        _ensure_finished_at(run)
        db.commit()
        return False
    if run.status in ("awaiting_patch_review", "awaiting_merge", "paused"):
        return False
    if _stage_rank(run.pipeline_stage) > _stage_rank(STAGE_CLONE):
        return False
    if run.status == "running" and run.pipeline_stage == STAGE_CLONE:
        if run.finished_at is not None:
            _repair_stale_clone(run)
            db.commit()
            return False
        _mark_running(run, STAGE_CLONE, started)
        db.commit()
        return True
    if run.status != "queued":
        return False
    _mark_running(run, STAGE_CLONE, started)
    db.commit()
    return True


def _claim_apply_stage(db, run: SandboxRun, started) -> bool:
    run = _lock_run(db, run)
    if run.status in TERMINAL_STATUSES:
        _ensure_finished_at(run)
        db.commit()
        return False
    if run.status == "awaiting_merge":
        return False
    if _stage_rank(run.pipeline_stage) > _stage_rank(STAGE_PATCH_APPLY):
        return False
    if run.status == "running" and run.pipeline_stage == STAGE_PATCH_APPLY:
        if run.finished_at is not None:
            _repair_stale_apply(db, run)
            db.commit()
            return False
        _mark_running(run, STAGE_PATCH_APPLY, started)
        db.commit()
        return True
    if run.status not in ("awaiting_patch_review", "queued"):
        return False
    if run.status == "queued" and _stage_rank(run.pipeline_stage) < _stage_rank(
        STAGE_PATCH_APPLY
    ):
        return False
    _mark_running(run, STAGE_PATCH_APPLY, started)
    db.commit()
    return True


def _claim_pr_stage(db, run: SandboxRun, started) -> bool:
    run = _lock_run(db, run)
    if run.pr_url:
        if run.status != "completed":
            run.status = "completed"
            _ensure_finished_at(run)
            db.commit()
        return False
    if run.status in TERMINAL_STATUSES:
        _ensure_finished_at(run)
        db.commit()
        return False
    if run.status == "running" and run.pipeline_stage == STAGE_PR:
        if run.finished_at is not None:
            run.status = "completed" if run.pr_url else "failed"
            db.commit()
            return False
        _mark_running(run, STAGE_PR, started)
        db.commit()
        return True
    if run.status != "awaiting_merge":
        return False
    _mark_running(run, STAGE_PR, started)
    db.commit()
    return True


def _latest_named_gate(db, run: SandboxRun, name: str) -> ApprovalGate | None:
    return (
        db.query(ApprovalGate)
        .filter(ApprovalGate.run_id == run.id, ApprovalGate.gate == name)
        .order_by(ApprovalGate.id.desc())
        .first()
    )


def _require_gate(db, run: SandboxRun, name: str) -> ApprovalGate:
    gate = _latest_named_gate(db, run, name)
    if gate is None or gate.status != "approved":
        raise RuntimeError(f"{name} requires Android approval")
    return gate


def _require_gate_or_retry(task, db, run: SandboxRun, name: str) -> ApprovalGate | None:
    gate = _latest_named_gate(db, run, name)
    db.refresh(run)
    if run.status in ("rejected", "killed") or run.control_state == "killed":
        return None
    if gate is not None and gate.status == "approved":
        return gate
    if gate is not None and gate.status == "pending":
        if task.request.called_directly:
            raise RuntimeError(f"{name} requires Android approval")
        try:
            raise task.retry(countdown=5)
        except MaxRetriesExceededError:
            logger.info(
                "still waiting for %s approval run_id=%s; leaving queued",
                name,
                run.id,
            )
            return None
    if gate is not None and gate.status in ("expired", "rejected"):
        return None
    raise RuntimeError(f"{name} requires Android approval")


def _control_or_stop(db, run: SandboxRun) -> bool:
    db.refresh(run)
    if run.control_state == "killed" or run.status == "killed":
        run.status = "killed"
        _ensure_finished_at(run)
        db.commit()
        return True
    if run.status == "rejected":
        return True
    if run.control_state == "paused" or run.status == "paused":
        run.status = "paused"
        db.commit()
        return True
    return False


def _clip_verify_output(text: str, limit: int = VERIFY_OUTPUT_LIMIT) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _as_patch_result(value) -> PatchGenerationResult:
    if isinstance(value, PatchGenerationResult):
        return value
    if isinstance(value, str):
        return PatchGenerationResult(diff=value, tokens_used=None)
    raise TypeError("generate_patch returned an unsupported result")


def _add_llm_usage(run: SandboxRun, tokens: int | None) -> None:
    if not tokens:
        return
    run.llm_tokens_used = (run.llm_tokens_used or 0) + int(tokens)


def _llm_budget_exceeded(run: SandboxRun) -> bool:
    budget = int(settings.llm_token_budget or 0)
    return budget > 0 and (run.llm_tokens_used or 0) >= budget


def _queue_patch_for_review(db, run: SandboxRun, diff: str, started) -> None:
    run.patch_attempts = (run.patch_attempts or 0) + 1
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


def _generate_retry_patch(
    db,
    run: SandboxRun,
    *,
    files: dict[str, str],
    latest,
    verify_err: str,
    started,
) -> None:
    previous_error = verify_err
    location_path = latest.diagnostic_path if latest else next(iter(files))
    source = files.get(location_path, "")
    diagnosis = _latest_diagnosis_text(db, run)
    test_source = latest.test_source if latest else ""
    while True:
        if run.patch_attempts >= MAX_PATCH_ATTEMPTS:
            _finish(run, started, "failed", "patch attempts exhausted")
            db.commit()
            return
        if _llm_budget_exceeded(run):
            _finish(run, started, "failed", "LLM token budget exceeded")
            db.commit()
            return
        try:
            generated = _as_patch_result(
                generate_patch(
                    path=location_path,
                    source=source,
                    test_source=test_source,
                    stderr=previous_error,
                    exception_type=None,
                    previous_error=previous_error,
                    files=files,
                    diagnosis=diagnosis,
                    tokens_used=run.llm_tokens_used or 0,
                )
            )
        except LlmNotConfigured:
            _finish(run, started, "failed", "LLM_API_KEY is not set")
            db.commit()
            return
        except LlmTokenBudgetExceeded:
            _finish(run, started, "failed", "LLM token budget exceeded")
            db.commit()
            return
        except LlmRequestTimeout as exc:
            previous_error = _clip_verify_output(str(exc))
            run.patch_attempts = (run.patch_attempts or 0) + 1
            db.add(
                PatchAttempt(
                    run_id=run.id,
                    attempt_number=run.patch_attempts,
                    diff=run.current_diff or "\n",
                    status="failed",
                    stderr=previous_error,
                )
            )
            db.commit()
            continue
        _add_llm_usage(run, generated.tokens_used)
        rejected = (
            EMPTY_PATCH_ERROR
            if not (generated.diff or "").strip()
            else IDENTICAL_PATCH_ERROR
            if diffs_are_identical(generated.diff, run.current_diff)
            else None
        )
        if rejected:
            previous_error = rejected
            run.patch_attempts = (run.patch_attempts or 0) + 1
            db.add(
                PatchAttempt(
                    run_id=run.id,
                    attempt_number=run.patch_attempts,
                    diff=generated.diff or (run.current_diff or "\n"),
                    status="failed",
                    stderr=rejected,
                )
            )
            db.commit()
            continue
        _queue_patch_for_review(db, run, generated.diff, started)
        return


def _verification_failure(*, apply_err: str, suite, full) -> str:
    if apply_err:
        return apply_err
    if suite is not None and not suite.reproduced and suite.exit_code != 0:
        parts = [f"reproduction test failed (exit {suite.exit_code})"]
        stdout = _clip_verify_output(suite.stdout)
        stderr = _clip_verify_output(suite.stderr)
        if stdout:
            parts.append(stdout)
        if stderr:
            parts.append(stderr)
        return "\n".join(parts).strip()
    if full is not None and full.ran_tests and full.exit_code != 0:
        parts = [f"full test suite failed (exit {full.exit_code})"]
        stdout = _clip_verify_output(full.stdout)
        stderr = _clip_verify_output(full.stderr)
        if stdout:
            parts.append(stdout)
        if stderr:
            parts.append(stderr)
        return "\n".join(parts).strip()
    if suite is not None and suite.stderr:
        return suite.stderr
    return ""


def _finish(run: SandboxRun, started, status: str, error: str | None = None):
    finished = datetime.now(timezone.utc)
    run.status = status
    run.error = error
    run.finished_at = finished
    run.duration_ms = int((finished - started).total_seconds() * 1000)


@celery_app.task(name="clone_and_index", max_retries=180, default_retry_delay=5)
def clone_and_index(run_id: int) -> None:
    db = SessionLocal()
    sandbox = None
    started = datetime.now(timezone.utc)
    log_stack = ExitStack()
    try:
        run = _load_run(db, run_id)
        gate = _require_gate_or_retry(clone_and_index, db, run, "sandbox_provision")
        if gate is None:
            return

        if _control_or_stop(db, run):
            return

        if not _claim_clone_stage(db, run, started):
            return

        notify_run_event(db, run, "Sandbox running", f"{run.repo} clone started")
        repo = (
            db.query(Repository)
            .filter(Repository.full_name == run.repo)
            .one()
        )
        token = get_installation_token_sync(repo.installation_id)
        log_stack.enter_context(e2b_runner.agent_log_scope(run.id, token))
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
                            diagnosis = None
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
                                    actor=ACTOR_WORKER,
                                    result=RESULT_SUCCESS,
                                )
                                db.commit()
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
                                generated = _as_patch_result(
                                    generate_patch(
                                        path=location.path,
                                        source=source,
                                        test_source=reproduction.test_source,
                                        stderr=result.stderr,
                                        exception_type=parsed_trace.exception_type,
                                        files=files,
                                        diagnosis=diagnosis,
                                        tokens_used=run.llm_tokens_used or 0,
                                    )
                                )
                                _add_llm_usage(run, generated.tokens_used)
                                _queue_patch_for_review(
                                    db, run, generated.diff, started
                                )
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
                            except LlmTokenBudgetExceeded:
                                _finish(
                                    run,
                                    started,
                                    "failed",
                                    "LLM token budget exceeded",
                                )
                                db.commit()
                                notify_run_event(
                                    db,
                                    run,
                                    "Run failed",
                                    "LLM token budget exceeded",
                                )
                                return
                            except LlmRequestTimeout as exc:
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
    except Retry:
        raise
    except MaxRetriesExceededError:
        logger.info("clone_and_index waiting on approval run_id=%s", run_id)
        return
    except Exception as exc:
        db.rollback()
        run = _load_run(db, run_id)
        if run.status in PROTECTED_STATUSES:
            return
        _finish(run, started, "failed", str(exc))
        db.commit()
        notify_run_event(db, run, "Run failed", str(exc)[:180])
        raise
    finally:
        log_stack.close()
        if sandbox is not None:
            try:
                sandbox.kill()
            except Exception:
                logger.exception("failed to kill sandbox")
        db.close()


def enqueue_clone_and_index(run_id: int) -> None:
    clone_and_index.delay(run_id)


@celery_app.task(name="apply_patch_and_verify")
def apply_patch_and_verify(run_id: int) -> None:
    db = SessionLocal()
    sandbox = None
    started = datetime.now(timezone.utc)
    log_stack = ExitStack()
    try:
        run = _load_run(db, run_id)
        _require_gate(db, run, PATCH_REVIEW_GATE)
        if _control_or_stop(db, run):
            return
        if not _claim_apply_stage(db, run, started):
            return
        if not run.current_diff:
            _finish(run, started, "failed", "no patch diff to apply")
            db.commit()
            return

        repo = (
            db.query(Repository)
            .filter(Repository.full_name == run.repo)
            .one()
        )
        token = get_installation_token_sync(repo.installation_id)
        log_stack.enter_context(e2b_runner.agent_log_scope(run.id, token))
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
        apply_ok, apply_err = apply_diff_in_sandbox(sandbox, run.current_diff)

        latest = (
            db.query(ReproductionAttempt)
            .filter(ReproductionAttempt.run_id == run.id)
            .order_by(ReproductionAttempt.id.desc())
            .first()
        )
        suite = None
        full = None
        if apply_ok and latest and latest.test_path and latest.test_source:
            suite = run_reproduction_test(
                sandbox,
                latest.test_path,
                latest.test_source,
                install_dependencies=False,
            )
            if suite.reproduced:
                tests_pass = False
            elif suite.passed_clean:
                full = run_full_test_suite(sandbox)
                tests_pass = extra_suite_ok(full)
            else:
                tests_pass = False
        else:
            tests_pass = False

        verify_err = _verification_failure(
            apply_err=apply_err,
            suite=suite,
            full=full,
        )
        if not tests_pass and not verify_err:
            verify_err = "verification could not be completed"
        record = (
            db.query(PatchAttempt)
            .filter(PatchAttempt.run_id == run.id)
            .order_by(PatchAttempt.id.desc())
            .first()
        )
        if record:
            record.status = "applied" if tests_pass else "failed"
            if tests_pass:
                record.stderr = apply_err or (suite.stderr if suite else None)
                if full is not None and not full.ran_tests:
                    record.stdout = ADDITIONAL_TESTS_SKIPPED
            else:
                record.stderr = verify_err or None
                if full is not None and full.ran_tests and full.exit_code != 0:
                    record.stdout = _clip_verify_output(full.stdout) or None
                elif suite is not None and suite.exit_code != 0:
                    record.stdout = _clip_verify_output(suite.stdout) or None
            db.commit()

        if tests_pass:
            run.pipeline_stage = STAGE_MERGE
            create_pending_gate(db, run, MERGE_GATE)
            _finish(run, started, "awaiting_merge")
            db.commit()
            notify_run_event(
                db,
                run,
                "Merge OTP required",
                extra_suite_merge_message(run.repo, full),
            )
            return

        if run.patch_attempts >= MAX_PATCH_ATTEMPTS:
            _finish(run, started, "failed", "patch attempts exhausted")
            db.commit()
            return

        _generate_retry_patch(
            db,
            run,
            files=files,
            latest=latest,
            verify_err=verify_err,
            started=started,
        )
    except Exception as exc:
        db.rollback()
        run = _load_run(db, run_id)
        if run.status in PROTECTED_STATUSES:
            return
        _finish(run, started, "failed", str(exc))
        db.commit()
        raise
    finally:
        log_stack.close()
        if sandbox is not None:
            try:
                sandbox.kill()
            except Exception:
                logger.exception("failed to kill sandbox")
        db.close()


@celery_app.task(name="open_github_pr")
def open_github_pr(run_id: int) -> None:
    db = SessionLocal()
    sandbox = None
    started = datetime.now(timezone.utc)
    log_stack = ExitStack()
    try:
        run = _load_run(db, run_id)
        _require_gate(db, run, MERGE_GATE)
        if _control_or_stop(db, run):
            return
        if not _claim_pr_stage(db, run, started):
            return
        repo = (
            db.query(Repository)
            .filter(Repository.full_name == run.repo)
            .one()
        )
        token = get_installation_token_sync(repo.installation_id)
        log_stack.enter_context(e2b_runner.agent_log_scope(run.id, token))
        branch = f"autopatch/run-{run.id}"
        sandbox, _files = e2b_runner.clone_and_read_sources_in_sandbox(
            clone_url=clone_url(run.repo),
            ref=run.ref,
            token=token,
        )
        run.e2b_sandbox_id = sandbox.sandbox_id
        db.commit()
        if run.current_diff:
            apply_ok, apply_err = apply_diff_in_sandbox(sandbox, run.current_diff)
            if not apply_ok:
                raise RuntimeError(apply_err or "git apply failed")
        e2b_runner.run_sandbox_command(
            sandbox,
            "cd /home/user/repo && "
            "git config user.email autopatch@local && "
            "git config user.name AutoPatch && "
            f"git checkout -b {branch} && "
            "git add -A && "
            "git commit -m 'fix: verified autopatch' && "
            f"git push origin {branch}",
            120,
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
        log_audit(
            db,
            "pr_opened",
            run.id,
            None,
            run.pr_url,
            actor=ACTOR_WORKER,
            result=RESULT_SUCCESS,
            event_metadata={"pr_url": run.pr_url} if run.pr_url else None,
        )
        db.commit()
        notify_run_event(db, run, "Pull request opened", run.pr_url or "")
    except Exception as exc:
        db.rollback()
        run = _load_run(db, run_id)
        if run.status in PROTECTED_STATUSES:
            return
        _finish(run, started, "failed", str(exc))
        db.commit()
        raise
    finally:
        log_stack.close()
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
        return len(expire_stale_gates(db, notify=False, recreate=False, limit=100))
    finally:
        db.close()
