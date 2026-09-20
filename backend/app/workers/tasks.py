import logging
import uuid
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone

from celery.exceptions import MaxRetriesExceededError, Retry
from sqlalchemy import or_

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
    PERMISSIONS_PR_WRITE,
    PERMISSIONS_REPO_READ,
    clone_url,
    installation_token_for_repo,
)
from app.services.gemini import diagnose_reproduction
from app.services.github_pr import (
    ReproductionTestPathError,
    build_pr_body,
    create_pull_request,
    validate_reproduction_test_path,
)
from app.services.harness import (
    ADDITIONAL_TESTS_SKIPPED,
    extra_suite_merge_message,
    extra_suite_ok,
    run_full_test_suite,
    run_reproduction_test,
    write_sandbox_file,
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
STAGE_LEASE_SECONDS = 120
STAGE_LEASE_SLACK_SECONDS = 5

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
        run.status = "failed"
        run.pipeline_stage = STAGE_CLONE
        if not run.error:
            run.error = "stale clone with no patch"
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


def _utc_now():
    return datetime.now(timezone.utc)


def _aware(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _new_stage_owner_token() -> str:
    return uuid.uuid4().hex


def _lease_is_active(expires_at, *, now=None) -> bool:
    if expires_at is None:
        return False
    now = now or _utc_now()
    return _aware(expires_at) > now


def _grant_stage_ownership(run: SandboxRun, stage: str, started) -> None:
    _mark_running(run, stage, started)
    run.stage_owner_token = _new_stage_owner_token()
    run.stage_lease_expires_at = _utc_now() + timedelta(seconds=STAGE_LEASE_SECONDS)


def _owned_run_filter(run_id: int, owner_token: str, *, now=None):
    now = now or _utc_now()
    return (
        SandboxRun.id == run_id,
        SandboxRun.stage_owner_token == owner_token,
        SandboxRun.status == "running",
        SandboxRun.stage_lease_expires_at.isnot(None),
        SandboxRun.stage_lease_expires_at > now,
    )


def _renew_stage_lease(
    db, run: SandboxRun, owner_token: str, *, stage: str | None = None
) -> bool:
    if not owner_token:
        return False
    now = _utc_now()
    slack = now - timedelta(seconds=STAGE_LEASE_SLACK_SECONDS)
    expected = stage or run.pipeline_stage
    expiry = now + timedelta(seconds=STAGE_LEASE_SECONDS)
    count = (
        db.query(SandboxRun)
        .filter(
            SandboxRun.id == run.id,
            SandboxRun.stage_owner_token == owner_token,
            SandboxRun.status == "running",
            SandboxRun.pipeline_stage == expected,
            or_(
                SandboxRun.stage_lease_expires_at.is_(None),
                SandboxRun.stage_lease_expires_at > slack,
            ),
        )
        .update(
            {"stage_lease_expires_at": expiry},
            synchronize_session="fetch",
        )
    )
    db.commit()
    if count != 1:
        return False
    run.stage_lease_expires_at = expiry
    return True


def _still_owns_stage(
    db, run: SandboxRun, owner_token: str, *, stage: str | None = None
) -> bool:
    if not owner_token:
        return False
    now = _utc_now()
    expected = stage or run.pipeline_stage
    row = (
        db.query(SandboxRun.id)
        .filter(
            SandboxRun.id == run.id,
            SandboxRun.stage_owner_token == owner_token,
            SandboxRun.status == "running",
            SandboxRun.pipeline_stage == expected,
            SandboxRun.stage_lease_expires_at.isnot(None),
            SandboxRun.stage_lease_expires_at > now,
        )
        .first()
    )
    return row is not None


def _owned_update(db, run: SandboxRun, owner_token: str, **fields) -> bool:
    if not owner_token or not fields:
        return False
    count = (
        db.query(SandboxRun)
        .filter(*_owned_run_filter(run.id, owner_token))
        .update(fields, synchronize_session="fetch")
    )
    if count != 1:
        return False
    for name, value in fields.items():
        setattr(run, name, value)
    return True


def _kill_local_sandbox(sandbox) -> None:
    if sandbox is None:
        return
    try:
        sandbox.kill()
    except Exception:
        logger.exception("failed to kill sandbox")


def _check_run_control(
    db, run: SandboxRun, owner_token: str, sandbox=None, *, stage: str | None = None
) -> bool:
    """Return whether this worker should continue.

    Observes committed pause/kill, then F18 ownership via the local token.
    A True result does not cancel a later external provider call.
    """
    if not owner_token:
        return False
    db.refresh(run)
    if run.control_state == "killed" or run.status == "killed":
        _kill_local_sandbox(sandbox)
        return False
    if run.control_state == "paused" or run.status == "paused":
        return False
    return _still_owns_stage(db, run, owner_token, stage=stage)


def _persist_created_sandbox_id(
    db, run: SandboxRun, owner_token: str, session, *, stage
) -> bool:
    if not _check_run_control(
        db, run, owner_token, sandbox=session, stage=stage
    ):
        if run.control_state != "killed" and run.status != "killed":
            _kill_local_sandbox(session)
        return False
    sandbox_id = getattr(session, "sandbox_id", None)
    if not sandbox_id or not _owned_update(
        db, run, owner_token, e2b_sandbox_id=sandbox_id
    ):
        _kill_local_sandbox(session)
        return False
    db.commit()
    return True


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
        if _lease_is_active(run.stage_lease_expires_at):
            return False
        _grant_stage_ownership(run, STAGE_CLONE, started)
        db.commit()
        return True
    if run.status != "queued":
        return False
    _grant_stage_ownership(run, STAGE_CLONE, started)
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
        if _lease_is_active(run.stage_lease_expires_at):
            return False
        _grant_stage_ownership(run, STAGE_PATCH_APPLY, started)
        db.commit()
        return True
    if run.status not in ("awaiting_patch_review", "queued"):
        return False
    if run.status == "queued" and _stage_rank(run.pipeline_stage) < _stage_rank(
        STAGE_PATCH_APPLY
    ):
        return False
    _grant_stage_ownership(run, STAGE_PATCH_APPLY, started)
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
        if _lease_is_active(run.stage_lease_expires_at):
            return False
        _grant_stage_ownership(run, STAGE_PR, started)
        db.commit()
        return True
    if run.status != "awaiting_merge":
        return False
    _grant_stage_ownership(run, STAGE_PR, started)
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
    text = e2b_runner.sanitize_log_text(text or "")
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


def _queue_patch_for_review(
    db, run: SandboxRun, diff: str, started, *, owner_token: str
) -> bool:
    if not _still_owns_stage(db, run, owner_token):
        return False
    attempts = (run.patch_attempts or 0) + 1
    if not _owned_update(
        db,
        run,
        owner_token,
        patch_attempts=attempts,
        current_diff=diff,
        pipeline_stage=STAGE_PATCH_REVIEW,
    ):
        return False
    db.add(
        PatchAttempt(
            run_id=run.id,
            attempt_number=attempts,
            diff=diff,
            status="pending_review",
        )
    )
    db.commit()
    if not _still_owns_stage(db, run, owner_token):
        return False
    create_pending_gate(db, run, PATCH_REVIEW_GATE)
    if not _finish(
        db, run, started, "awaiting_patch_review", owner_token=owner_token
    ):
        return False
    db.commit()
    return True


def _generate_retry_patch(
    db,
    run: SandboxRun,
    *,
    files: dict[str, str],
    latest,
    verify_err: str,
    started,
    owner_token: str,
    sandbox=None,
) -> None:
    previous_error = verify_err
    location_path = latest.diagnostic_path if latest else next(iter(files))
    source = files.get(location_path, "")
    diagnosis = _latest_diagnosis_text(db, run)
    test_source = latest.test_source if latest else ""
    while True:
        if not _renew_stage_lease(db, run, owner_token, stage=STAGE_PATCH_APPLY):
            return
        if not _check_run_control(
            db, run, owner_token, sandbox, stage=STAGE_PATCH_APPLY
        ):
            return
        if run.patch_attempts >= MAX_PATCH_ATTEMPTS:
            _finish(
                db,
                run,
                started,
                "failed",
                "patch attempts exhausted",
                owner_token=owner_token,
            )
            db.commit()
            return
        if _llm_budget_exceeded(run):
            _finish(
                db,
                run,
                started,
                "failed",
                "LLM token budget exceeded",
                owner_token=owner_token,
            )
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
            _finish(
                db,
                run,
                started,
                "failed",
                "LLM_API_KEY is not set",
                owner_token=owner_token,
            )
            db.commit()
            return
        except LlmTokenBudgetExceeded:
            _finish(
                db,
                run,
                started,
                "failed",
                "LLM token budget exceeded",
                owner_token=owner_token,
            )
            db.commit()
            return
        except LlmRequestTimeout as exc:
            previous_error = _clip_verify_output(str(exc))
            if not _still_owns_stage(db, run, owner_token, stage=STAGE_PATCH_APPLY):
                return
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
        if not _still_owns_stage(db, run, owner_token, stage=STAGE_PATCH_APPLY):
            return
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
        _queue_patch_for_review(
            db, run, generated.diff, started, owner_token=owner_token
        )
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
        return _clip_verify_output(suite.stderr)
    return ""


def _finish(
    db,
    run: SandboxRun,
    started,
    status: str,
    error: str | None = None,
    *,
    owner_token: str | None,
) -> bool:
    if not owner_token:
        return False
    finished = _utc_now()
    start = started or run.started_at
    if start is not None and getattr(start, "tzinfo", None) is None:
        start = start.replace(tzinfo=timezone.utc)
    duration = None
    if start is not None:
        duration = int((finished - start).total_seconds() * 1000)
    count = (
        db.query(SandboxRun)
        .filter(*_owned_run_filter(run.id, owner_token))
        .update(
            {
                "status": status,
                "error": error,
                "finished_at": finished,
                "duration_ms": duration,
                "stage_owner_token": None,
                "stage_lease_expires_at": None,
            },
            synchronize_session="fetch",
        )
    )
    if count != 1:
        return False
    run.status = status
    run.error = error
    run.finished_at = finished
    run.duration_ms = duration
    run.stage_owner_token = None
    run.stage_lease_expires_at = None
    return True


def _persisted_pr_url(db, run_id: int) -> str | None:
    return (
        db.query(SandboxRun.pr_url)
        .filter(SandboxRun.id == run_id)
        .scalar()
    )


def _required_source_sha(run: SandboxRun) -> str:
    try:
        return e2b_runner.parse_git_sha(run.source_sha)
    except ValueError as exc:
        raise RuntimeError("source_sha is required") from exc


def _clone_run_sources(
    run: SandboxRun, token: str, *, sha: str | None = None, on_created=None
):
    return e2b_runner.clone_and_read_sources_in_sandbox(
        clone_url=clone_url(run.repo),
        ref=run.ref,
        token=token,
        sha=sha,
        on_created=on_created,
    )


@celery_app.task(name="clone_and_index", max_retries=180, default_retry_delay=5)
def clone_and_index(run_id: int) -> None:
    db = SessionLocal()
    sandbox = None
    started = datetime.now(timezone.utc)
    log_stack = ExitStack()
    owner_token = None
    try:
        run = _load_run(db, run_id)
        gate = _require_gate_or_retry(clone_and_index, db, run, "sandbox_provision")
        if gate is None:
            return

        if _control_or_stop(db, run):
            return

        if not _claim_clone_stage(db, run, started):
            return
        owner_token = run.stage_owner_token

        notify_run_event(db, run, "Sandbox running", f"{run.repo} clone started")
        repo = (
            db.query(Repository)
            .filter(Repository.full_name == run.repo)
            .one()
        )
        token = installation_token_for_repo(
            repo.installation_id,
            run.repo,
            PERMISSIONS_REPO_READ,
        )
        log_stack.enter_context(e2b_runner.agent_log_scope(run.id, token))
        pin = None
        if run.source_sha:
            try:
                pin = e2b_runner.parse_git_sha(run.source_sha)
            except ValueError:
                pin = None
        if not _renew_stage_lease(db, run, owner_token, stage=STAGE_CLONE):
            return
        if not _check_run_control(
            db, run, owner_token, sandbox, stage=STAGE_CLONE
        ):
            return
        sandbox, files = _clone_run_sources(
            run,
            token,
            sha=pin,
            on_created=lambda session: _persist_created_sandbox_id(
                db, run, owner_token, session, stage=STAGE_CLONE
            ),
        )
        if files is None:
            return
        head = e2b_runner.checkout_head_sha(sandbox)
        if pin and head != pin:
            raise RuntimeError(
                f"checkout HEAD {head} does not match source_sha {pin}"
            )
        if not _owned_update(
            db,
            run,
            owner_token,
            source_sha=head,
            e2b_sandbox_id=sandbox.sandbox_id,
        ):
            return
        db.commit()

        install_code, _install_out, install_err = (
            e2b_runner.install_project_dependencies(sandbox)
        )
        if install_code != 0:
            if _finish(
                db,
                run,
                started,
                "failed",
                f"dependency install failed: {install_err[:500]}",
                owner_token=owner_token,
            ):
                db.commit()
                notify_run_event(db, run, "Run failed", "dependency install failed")
            return

        if _control_or_stop(db, run):
            return
        if not _check_run_control(
            db, run, owner_token, sandbox, stage=STAGE_CLONE
        ):
            return

        if not _renew_stage_lease(db, run, owner_token, stage=STAGE_CLONE):
            return
        rows = indexer.index_files(files)
        if not _still_owns_stage(db, run, owner_token, stage=STAGE_CLONE):
            return
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

        def fail_incomplete(reason: str) -> None:
            if _finish(db, run, started, "failed", reason, owner_token=owner_token):
                db.commit()
                notify_run_event(db, run, "Run failed", reason[:180])

        if not run.stack_trace:
            fail_incomplete("missing stack_trace")
            return

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
        if not locations:
            fail_incomplete("no locateable frames")
            return

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
        if source is None:
            fail_incomplete("source file not found")
            return

        if not _renew_stage_lease(db, run, owner_token, stage=STAGE_CLONE):
            return
        try:
            reproduction = synthesize_repro(
                location=location,
                source=source,
                exception_type=parsed_trace.exception_type,
                message=parsed_trace.message,
            )
        except ValueError as exc:
            if _still_owns_stage(db, run, owner_token, stage=STAGE_CLONE):
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
                fail_incomplete(str(exc) or "reproduction synthesis failed")
            return

        result = run_reproduction_test(
            sandbox=sandbox,
            test_path=reproduction.test_path,
            test_source=reproduction.test_source,
            install_dependencies=False,
        )
        if not _still_owns_stage(db, run, owner_token, stage=STAGE_CLONE):
            return
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

        if not result.reproduced:
            fail_incomplete("bug not reproduced")
            return

        diagnosis = None
        try:
            if not _renew_stage_lease(db, run, owner_token, stage=STAGE_CLONE):
                return
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
            if _still_owns_stage(db, run, owner_token, stage=STAGE_CLONE):
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
            fail_incomplete("stopped after reproduction")
            return
        try:
            if not _renew_stage_lease(db, run, owner_token, stage=STAGE_CLONE):
                return
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
            if not _still_owns_stage(db, run, owner_token, stage=STAGE_CLONE):
                return
            queued = _queue_patch_for_review(
                db, run, generated.diff, started, owner_token=owner_token
            )
            if queued:
                notify_run_event(
                    db,
                    run,
                    "Patch ready for review",
                    f"{run.repo} diff waiting on Android",
                    {"has_diff": "true"},
                )
            return
        except LlmNotConfigured as exc:
            if _finish(db, run, started, "failed", str(exc), owner_token=owner_token):
                db.commit()
                notify_run_event(
                    db, run, "Run failed", str(exc)[:180]
                )
            return
        except LlmTokenBudgetExceeded:
            if _finish(
                db,
                run,
                started,
                "failed",
                "LLM token budget exceeded",
                owner_token=owner_token,
            ):
                db.commit()
                notify_run_event(
                    db,
                    run,
                    "Run failed",
                    "LLM token budget exceeded",
                )
            return
        except LlmRequestTimeout as exc:
            if _finish(db, run, started, "failed", str(exc), owner_token=owner_token):
                db.commit()
                notify_run_event(
                    db, run, "Run failed", str(exc)[:180]
                )
            return
        except Exception:
            logger.exception("patch generation failed")
            if _finish(
                db,
                run,
                started,
                "failed",
                "patch generation failed",
                owner_token=owner_token,
            ):
                db.commit()
                notify_run_event(
                    db,
                    run,
                    "Run failed",
                    "patch generation failed",
                )
            return
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
        if owner_token and _finish(
            db, run, started, "failed", str(exc), owner_token=owner_token
        ):
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
    owner_token = None
    try:
        run = _load_run(db, run_id)
        _require_gate(db, run, PATCH_REVIEW_GATE)
        if _control_or_stop(db, run):
            return
        if not _claim_apply_stage(db, run, started):
            return
        owner_token = run.stage_owner_token
        if not run.current_diff:
            if _finish(
                db, run, started, "failed", "no patch diff to apply",
                owner_token=owner_token,
            ):
                db.commit()
            return
        try:
            source_sha = _required_source_sha(run)
        except RuntimeError:
            if _finish(
                db, run, started, "failed", "source_sha is required",
                owner_token=owner_token,
            ):
                db.commit()
            return

        repo = (
            db.query(Repository)
            .filter(Repository.full_name == run.repo)
            .one()
        )
        token = installation_token_for_repo(
            repo.installation_id,
            run.repo,
            PERMISSIONS_REPO_READ,
        )
        log_stack.enter_context(e2b_runner.agent_log_scope(run.id, token))
        if not _renew_stage_lease(db, run, owner_token, stage=STAGE_PATCH_APPLY):
            return
        if not _check_run_control(
            db, run, owner_token, sandbox, stage=STAGE_PATCH_APPLY
        ):
            return
        sandbox, files = _clone_run_sources(
            run,
            token,
            sha=source_sha,
            on_created=lambda session: _persist_created_sandbox_id(
                db, run, owner_token, session, stage=STAGE_PATCH_APPLY
            ),
        )
        if files is None:
            return
        head = e2b_runner.checkout_head_sha(sandbox)
        if head != source_sha:
            raise RuntimeError(
                f"checkout HEAD {head} does not match source_sha {source_sha}"
            )
        if not _owned_update(
            db, run, owner_token, e2b_sandbox_id=sandbox.sandbox_id
        ):
            return
        db.commit()
        install_code, _out, install_err = e2b_runner.install_project_dependencies(
            sandbox
        )
        if install_code != 0:
            if _finish(
                db,
                run,
                started,
                "failed",
                f"dependency install failed: {install_err[:500]}",
                owner_token=owner_token,
            ):
                db.commit()
            return
        latest = (
            db.query(ReproductionAttempt)
            .filter(ReproductionAttempt.run_id == run.id)
            .order_by(ReproductionAttempt.id.desc())
            .first()
        )
        if not _renew_stage_lease(db, run, owner_token, stage=STAGE_PATCH_APPLY):
            return
        allowed_path = ""
        if latest is not None and latest.diagnostic_path:
            allowed_path = latest.diagnostic_path
        if not allowed_path:
            apply_ok, apply_err = False, ""
        else:
            if not _check_run_control(
                db, run, owner_token, sandbox, stage=STAGE_PATCH_APPLY
            ):
                return
            apply_ok, apply_err = apply_diff_in_sandbox(
                sandbox, run.current_diff, allowed_path=allowed_path
            )
        suite = None
        full = None
        if apply_ok and latest and latest.test_path and latest.test_source:
            if not _renew_stage_lease(db, run, owner_token, stage=STAGE_PATCH_APPLY):
                return
            if not _check_run_control(
                db, run, owner_token, sandbox, stage=STAGE_PATCH_APPLY
            ):
                return
            suite = run_reproduction_test(
                sandbox,
                latest.test_path,
                latest.test_source,
                install_dependencies=False,
            )
            if suite.reproduced:
                tests_pass = False
            elif suite.passed_clean:
                if not _check_run_control(
                    db, run, owner_token, sandbox, stage=STAGE_PATCH_APPLY
                ):
                    return
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
        if not _check_run_control(
            db, run, owner_token, sandbox, stage=STAGE_PATCH_APPLY
        ):
            return
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
            if not _check_run_control(
                db, run, owner_token, sandbox, stage=STAGE_PATCH_APPLY
            ):
                return
            if not _owned_update(
                db, run, owner_token, pipeline_stage=STAGE_MERGE
            ):
                return
            if not _still_owns_stage(db, run, owner_token):
                return
            create_pending_gate(db, run, MERGE_GATE)
            if _finish(
                db, run, started, "awaiting_merge", owner_token=owner_token
            ):
                db.commit()
                notify_run_event(
                    db,
                    run,
                    "Merge OTP required",
                    extra_suite_merge_message(run.repo, full),
                )
            return

        if run.patch_attempts >= MAX_PATCH_ATTEMPTS:
            if _finish(
                db,
                run,
                started,
                "failed",
                "patch attempts exhausted",
                owner_token=owner_token,
            ):
                db.commit()
            return

        if not _renew_stage_lease(db, run, owner_token, stage=STAGE_PATCH_APPLY):
            return
        if not _check_run_control(
            db, run, owner_token, sandbox, stage=STAGE_PATCH_APPLY
        ):
            return
        _generate_retry_patch(
            db,
            run,
            files=files,
            latest=latest,
            verify_err=verify_err,
            started=started,
            owner_token=owner_token,
            sandbox=sandbox,
        )
    except Exception as exc:
        db.rollback()
        run = _load_run(db, run_id)
        if run.status in PROTECTED_STATUSES:
            return
        if owner_token and _finish(
            db, run, started, "failed", str(exc), owner_token=owner_token
        ):
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
    owner_token = None
    try:
        run = _load_run(db, run_id)
        _require_gate(db, run, MERGE_GATE)
        if _control_or_stop(db, run):
            return
        if not _claim_pr_stage(db, run, started):
            return
        owner_token = run.stage_owner_token
        try:
            source_sha = _required_source_sha(run)
        except RuntimeError:
            if _finish(
                db, run, started, "failed", "source_sha is required",
                owner_token=owner_token,
            ):
                db.commit()
            return
        latest = (
            db.query(ReproductionAttempt)
            .filter(ReproductionAttempt.run_id == run.id)
            .order_by(ReproductionAttempt.id.desc())
            .first()
        )
        if (
            latest is None
            or not (latest.test_path or "").strip()
            or not (latest.test_source or "").strip()
        ):
            if _finish(
                db,
                run,
                started,
                "failed",
                "cannot create PR: verified reproduction test is missing",
                owner_token=owner_token,
            ):
                db.commit()
            return
        repo = (
            db.query(Repository)
            .filter(Repository.full_name == run.repo)
            .one()
        )
        read_token = installation_token_for_repo(
            repo.installation_id,
            run.repo,
            PERMISSIONS_REPO_READ,
        )
        log_stack.enter_context(e2b_runner.agent_log_scope(run.id, read_token))
        branch = f"autopatch/run-{run.id}"
        if not _renew_stage_lease(db, run, owner_token, stage=STAGE_PR):
            return
        if not _check_run_control(db, run, owner_token, sandbox, stage=STAGE_PR):
            return
        sandbox, _files = _clone_run_sources(
            run,
            read_token,
            sha=source_sha,
            on_created=lambda session: _persist_created_sandbox_id(
                db, run, owner_token, session, stage=STAGE_PR
            ),
        )
        if _files is None:
            return
        head = e2b_runner.checkout_head_sha(sandbox)
        if head != source_sha:
            raise RuntimeError(
                f"checkout HEAD {head} does not match source_sha {source_sha}"
            )
        if not _owned_update(
            db, run, owner_token, e2b_sandbox_id=sandbox.sandbox_id
        ):
            return
        db.commit()
        if run.current_diff:
            if not _renew_stage_lease(db, run, owner_token, stage=STAGE_PR):
                return
            if not _check_run_control(
                db, run, owner_token, sandbox, stage=STAGE_PR
            ):
                return
            allowed_path = ""
            if latest.diagnostic_path:
                allowed_path = latest.diagnostic_path
            apply_ok, apply_err = apply_diff_in_sandbox(
                sandbox, run.current_diff, allowed_path=allowed_path
            )
            if not apply_ok:
                raise RuntimeError(apply_err or "git apply failed")
        applied_head = e2b_runner.checkout_head_sha(sandbox)
        if applied_head != source_sha:
            raise RuntimeError(
                f"checkout HEAD {applied_head} does not match source_sha {source_sha}"
            )
        try:
            test_path = validate_reproduction_test_path(latest.test_path)
        except ReproductionTestPathError as exc:
            if _finish(
                db, run, started, "failed", str(exc), owner_token=owner_token
            ):
                db.commit()
            return
        if not _renew_stage_lease(db, run, owner_token, stage=STAGE_PR):
            return
        if not _check_run_control(db, run, owner_token, sandbox, stage=STAGE_PR):
            return
        write_sandbox_file(
            sandbox,
            f"/home/user/repo/{test_path}",
            latest.test_source,
        )
        if not _check_run_control(db, run, owner_token, sandbox, stage=STAGE_PR):
            return
        e2b_runner.run_sandbox_command(
            sandbox,
            "cd /home/user/repo && "
            "git config user.email autopatch@local && "
            "git config user.name AutoPatch && "
            f"git checkout -b {branch} && "
            "git add -A && "
            "git commit -m 'fix: verified autopatch'",
            120,
        )
        parent = e2b_runner.commit_parent_sha(sandbox)
        if parent != source_sha:
            raise RuntimeError(
                f"patch commit parent {parent} does not match source_sha {source_sha}"
            )
        write_token = installation_token_for_repo(
            repo.installation_id,
            run.repo,
            PERMISSIONS_PR_WRITE,
        )
        log_stack.enter_context(e2b_runner.agent_log_scope(run.id, write_token))
        if not _renew_stage_lease(db, run, owner_token, stage=STAGE_PR):
            return
        if _persisted_pr_url(db, run.id):
            return
        if not _check_run_control(db, run, owner_token, sandbox, stage=STAGE_PR):
            return
        e2b_runner.push_branch(sandbox, branch, write_token)
        patch = _latest_patch_attempt(db, run)
        merge_gate = (
            db.query(ApprovalGate)
            .filter(
                ApprovalGate.run_id == run.id,
                ApprovalGate.gate == MERGE_GATE,
            )
            .order_by(ApprovalGate.id.desc())
            .first()
        )
        if not _renew_stage_lease(db, run, owner_token, stage=STAGE_PR):
            return
        existing_pr = _persisted_pr_url(db, run.id)
        if existing_pr:
            if not _check_run_control(
                db, run, owner_token, sandbox, stage=STAGE_PR
            ):
                return
            if _owned_update(db, run, owner_token, pr_url=existing_pr):
                if _finish(
                    db, run, started, "completed", owner_token=owner_token
                ):
                    db.commit()
            return
        if not _check_run_control(db, run, owner_token, sandbox, stage=STAGE_PR):
            return
        pr = create_pull_request(
            token=write_token,
            repo=run.repo,
            title=f"AutoPatch: verified fix for run {run.id}",
            body=build_pr_body(
                run_id=run.id,
                repo=run.repo,
                ref=run.ref,
                source_sha=run.source_sha,
                diagnostic_path=latest.diagnostic_path,
                test_path=test_path,
                reproduced=latest.reproduced,
                reproduction_exit_code=latest.exit_code,
                patch_attempt_id=patch.id if patch is not None else None,
                patch_status=patch.status if patch is not None else None,
                patch_stdout=patch.stdout if patch is not None else None,
                current_diff=run.current_diff,
                merge_approved_at=(
                    merge_gate.approved_at if merge_gate is not None else None
                ),
                approval_device_id=(
                    merge_gate.device_id if merge_gate is not None else None
                ),
            ),
            head=branch,
            base=run.ref or "main",
        )
        pr_url = pr.get("html_url")
        if not _check_run_control(db, run, owner_token, sandbox, stage=STAGE_PR):
            return
        if not _owned_update(db, run, owner_token, pr_url=pr_url):
            return
        if not _finish(db, run, started, "completed", owner_token=owner_token):
            return
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
        if owner_token and _finish(
            db, run, started, "failed", str(exc), owner_token=owner_token
        ):
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
