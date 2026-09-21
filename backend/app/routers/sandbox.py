from datetime import datetime, timezone
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import func
from sqlalchemy.orm import Session, noload

from app.auth import (
    issue_ws_ticket,
    require_api_key,
    secrets_match,
    ticket_from_ws_protocols,
    verify_ws_ticket,
    ws_api_key_header_allowed,
    ws_subprotocol_for_ticket,
)
from app.config import settings
from app.db import get_db
from app.models import (
    ApprovalGate,
    AuditEvent,
    Device,
    PatchAttempt,
    ReproductionAttempt,
    Repository,
    SandboxRun,
    Symbol,
)
from app.schemas import ApprovalRequest, RunControlRequest, SandboxRunCreate
from app.services.approval import (
    MERGE_GATE,
    PATCH_REVIEW_GATE,
    SANDBOX_PROVISION_GATE,
    STAGE_CLONE,
    STAGE_MERGE,
    STAGE_PATCH_APPLY,
    STAGE_PATCH_REVIEW,
    STAGE_PR,
    STAGE_PROVISION,
    ApprovalDeviceUnavailable,
    apply_gate_expiry,
    create_pending_gate,
    create_pending_provision_gate,
    expire_stale_gates,
    gate_is_expired,
    try_claim_pending_gate,
)
from app.services.audit import (
    ACTOR_ANDROID,
    RESULT_REJECTED,
    RESULT_SUCCESS,
    consume_device_authorization,
    device_auth_factor,
    log_audit,
)
from app.services.e2b_runner import sanitize_log_text
from app.services.events import publish_run_update
from app.services.providers import get_sandbox_provider
from app.workers.tasks import (
    TERMINAL_STATUSES,
    _ensure_finished_at,
    apply_patch_and_verify,
    clone_and_index,
    open_github_pr,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _enqueue(task, run_id: int) -> None:
    try:
        result = task.delay(run_id)
    except Exception as exc:
        logger.exception(
            "failed to publish celery task %s run_id=%s",
            getattr(task, "name", task),
            run_id,
        )
        raise HTTPException(
            status_code=503,
            detail="failed to dispatch run task",
        ) from exc
    logger.info(
        "published celery task %s run_id=%s task_id=%s queue=celery",
        getattr(task, "name", task),
        run_id,
        getattr(result, "id", None),
    )


def _enqueue_for_gate(gate_name: str, run_id: int) -> None:
    task = _task_for_gate(gate_name)
    if task is not None:
        _enqueue(task, run_id)


def _task_for_gate(gate_name: str):
    if gate_name == SANDBOX_PROVISION_GATE:
        return clone_and_index
    if gate_name == PATCH_REVIEW_GATE:
        return apply_patch_and_verify
    if gate_name == MERGE_GATE:
        return open_github_pr
    return None


def _task_for_approved_idle_run(run: SandboxRun, gate_name: str):
    """Return a Celery task only when re-dispatch is a safe idle retry."""
    if run.pr_url:
        return None
    if run.control_state == "killed" or run.status in TERMINAL_STATUSES:
        return None
    if run.status in ("running", "paused"):
        return None
    stage = run.pipeline_stage or STAGE_PROVISION
    if gate_name == SANDBOX_PROVISION_GATE:
        if run.status == "queued" and stage in (STAGE_PROVISION, STAGE_CLONE):
            return clone_and_index
        return None
    if gate_name == PATCH_REVIEW_GATE:
        if run.status in ("queued", "awaiting_patch_review") and stage in (
            STAGE_PATCH_REVIEW,
            STAGE_PATCH_APPLY,
        ):
            return apply_patch_and_verify
        return None
    if gate_name == MERGE_GATE:
        if run.status == "awaiting_merge" and stage in (STAGE_MERGE, STAGE_PR):
            return open_github_pr
        return None
    return None


def _redispatch_approved_idle(run: SandboxRun, gate_name: str) -> None:
    task = _task_for_approved_idle_run(run, gate_name)
    if task is not None:
        _enqueue(task, run.id)


def _require_device(db: Session, device_id: str) -> Device:
    device = (
        db.query(Device)
        .filter(Device.device_id == device_id)
        .one_or_none()
    )
    if device is None or not device.totp_secret:
        raise HTTPException(status_code=404, detail="device not registered")
    if device.revoked_at is not None:
        raise HTTPException(status_code=403, detail="device revoked")
    return device


def _require_gate_device(gate: ApprovalGate, device_id: str) -> None:
    if not gate.device_id or gate.device_id != device_id:
        raise HTTPException(
            status_code=403,
            detail="device is not authorized for this gate",
        )


def _create_pending_gate_http(
    db: Session,
    run: SandboxRun,
    name: str,
    notify: bool = True,
) -> ApprovalGate:
    try:
        return create_pending_gate(db, run, name, notify=notify)
    except ApprovalDeviceUnavailable as exc:
        raise HTTPException(status_code=503, detail=exc.detail) from exc


def _require_run(db: Session, run_id: int) -> SandboxRun:
    run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


def _pending_gate(db: Session, run: SandboxRun, gate_name: str | None = None):
    query = db.query(ApprovalGate).filter(
        ApprovalGate.run_id == run.id,
        ApprovalGate.status == "pending",
    )
    if gate_name:
        query = query.filter(ApprovalGate.gate == gate_name)
    return query.order_by(ApprovalGate.id.desc()).first()


def _expire_if_needed(db: Session, gate: ApprovalGate) -> None:
    if gate_is_expired(gate) and gate.status == "pending":
        apply_gate_expiry(db, gate, recreate=False, notify=False)
        raise HTTPException(
            status_code=409,
            detail="approval gate has expired",
        )


def _unpause_on_approve(run: SandboxRun) -> None:
    if run.control_state == "paused":
        run.control_state = "active"


def _kill_sandbox(run: SandboxRun) -> None:
    if not run.e2b_sandbox_id:
        return
    get_sandbox_provider().kill(run.e2b_sandbox_id)


def serialize_runs(runs: list[SandboxRun]) -> dict:
    return {
        "runs": [
            {
                "id": run.id,
                "repo": run.repo,
                "ref": run.ref,
                "status": run.status,
                "current_diff": run.current_diff,
                "pr_url": run.pr_url,
                "control_state": run.control_state,
                "pipeline_stage": run.pipeline_stage,
                "error": run.error,
                "patch_attempts": run.patch_attempts,
                "duration_ms": run.duration_ms,
                "started_at": (
                    run.started_at.isoformat() if run.started_at else None
                ),
                "finished_at": (
                    run.finished_at.isoformat() if run.finished_at else None
                ),
            }
            for run in runs
        ]
    }


def _latest_gate(db: Session, run: SandboxRun, name: str) -> ApprovalGate | None:
    return (
        db.query(ApprovalGate)
        .filter(ApprovalGate.run_id == run.id, ApprovalGate.gate == name)
        .order_by(ApprovalGate.id.desc())
        .first()
    )


def _ensure_pending_gate(db: Session, run: SandboxRun, name: str) -> None:
    gate = _latest_gate(db, run, name)
    if gate is not None and gate.status == "pending":
        return
    _create_pending_gate_http(db, run, name)


def resume_paused_run(run: SandboxRun, db: Session):
    """Mutate the run for resume. Return the Celery task to publish after commit."""
    run.control_state = "active"
    stage = run.pipeline_stage or STAGE_PROVISION
    if stage == STAGE_PROVISION:
        run.status = "queued"
        gate = _latest_gate(db, run, SANDBOX_PROVISION_GATE)
        if gate is not None and gate.status == "approved":
            return clone_and_index
        _ensure_pending_gate(db, run, SANDBOX_PROVISION_GATE)
        return None
    if stage == STAGE_CLONE:
        run.status = "queued"
        return clone_and_index
    if stage == STAGE_PATCH_REVIEW:
        run.status = "awaiting_patch_review"
        gate = _latest_gate(db, run, PATCH_REVIEW_GATE)
        if gate is not None and gate.status == "approved":
            return apply_patch_and_verify
        _ensure_pending_gate(db, run, PATCH_REVIEW_GATE)
        return None
    if stage == STAGE_PATCH_APPLY:
        run.status = "queued"
        return apply_patch_and_verify
    if stage == STAGE_MERGE:
        run.status = "awaiting_merge"
        gate = _latest_gate(db, run, MERGE_GATE)
        if gate is not None and gate.status == "approved":
            return open_github_pr
        _ensure_pending_gate(db, run, MERGE_GATE)
        return None
    if stage == STAGE_PR:
        run.status = "awaiting_merge"
        return open_github_pr
    run.status = "queued"
    return clone_and_index


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
        stack_trace=body.stack_trace,
        pipeline_stage=STAGE_PROVISION,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        gate = create_pending_provision_gate(db, run)
    except ApprovalDeviceUnavailable as exc:
        raise HTTPException(status_code=503, detail=exc.detail) from exc
    _enqueue(clone_and_index, run.id)
    logger.info(
        "sandbox run %s queued with %s gate %s; clone_and_index published to celery",
        run.id,
        gate.gate,
        gate.id,
    )
    return {
        "id": run.id,
        "status": run.status,
        "pipeline_stage": run.pipeline_stage,
        "approval_gate": gate.gate,
        "approval_status": gate.status,
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
    run = _require_run(db, run_id)
    if run.control_state == "killed":
        raise HTTPException(status_code=409, detail="run was killed")

    gate = _pending_gate(db, run)
    if gate is None:
        latest = (
            db.query(ApprovalGate)
            .filter(ApprovalGate.run_id == run.id)
            .order_by(ApprovalGate.id.desc())
            .first()
        )
        if latest is not None and latest.status == "approved":
            if not latest.device_id or latest.device_id != body.device_id:
                raise HTTPException(
                    status_code=403,
                    detail="device is not authorized for this gate",
                )
            _redispatch_approved_idle(run, latest.gate)
            return {
                "ok": True,
                "run_id": run.id,
                "gate": latest.gate,
                "status": latest.status,
            }
        raise HTTPException(status_code=404, detail="approval gate not found")

    _expire_if_needed(db, gate)
    device = _require_device(db, body.device_id)
    _require_gate_device(gate, device.device_id)
    payload = f"{device.device_id}|{run.id}|{gate.gate}"
    auth_factor = device_auth_factor(
        device,
        body.otp_code,
        body.approval_token,
        body.token_ts,
        payload,
    )
    if auth_factor is None:
        raise HTTPException(status_code=401, detail="invalid otp")
    if not consume_device_authorization(
        db,
        device,
        payload,
        body.otp_code,
        body.approval_token,
        auth_factor=auth_factor,
    ):
        raise HTTPException(status_code=401, detail="invalid otp")

    claimed = try_claim_pending_gate(db, gate.id, device.device_id)
    if claimed is None:
        _redispatch_approved_idle(run, gate.gate)
        return {
            "ok": True,
            "run_id": run.id,
            "gate": gate.gate,
            "status": "approved",
        }

    _unpause_on_approve(run)
    if run.status in ("paused",):
        run.status = "queued"
    log_audit(
        db,
        "approve",
        run.id,
        device.device_id,
        claimed.gate,
        actor=ACTOR_ANDROID,
        result=RESULT_SUCCESS,
        event_metadata={"gate": claimed.gate},
    )
    db.commit()
    _enqueue_for_gate(claimed.gate, run.id)
    publish_run_update(
        {
            "type": "approval",
            "run_id": run.id,
            "status": run.status,
            "gate": claimed.gate,
            "gate_status": claimed.status,
        }
    )
    return {
        "ok": True,
        "run_id": run.id,
        "gate": claimed.gate,
        "status": claimed.status,
    }


@router.post(
    "/v1/sandbox/runs/{run_id}/rejection",
    dependencies=[Depends(require_api_key)],
)
def reject_sandbox(
    run_id: int,
    body: ApprovalRequest,
    db: Session = Depends(get_db),
):
    run = _require_run(db, run_id)
    gate = _pending_gate(db, run)
    if gate is None:
        latest = (
            db.query(ApprovalGate)
            .filter(ApprovalGate.run_id == run.id)
            .order_by(ApprovalGate.id.desc())
            .first()
        )
        if latest is not None and latest.status == "rejected":
            if not latest.device_id or latest.device_id != body.device_id:
                raise HTTPException(
                    status_code=403,
                    detail="device is not authorized for this gate",
                )
            return {"ok": True, "run_id": run.id, "status": "rejected"}
        raise HTTPException(status_code=404, detail="approval gate not found")
    _expire_if_needed(db, gate)
    device = _require_device(db, body.device_id)
    _require_gate_device(gate, device.device_id)
    payload = f"{device.device_id}|{run.id}|{gate.gate}"
    auth_factor = device_auth_factor(
        device,
        body.otp_code,
        body.approval_token,
        body.token_ts,
        payload,
    )
    if auth_factor is None:
        raise HTTPException(status_code=401, detail="invalid otp")
    if not consume_device_authorization(
        db,
        device,
        payload,
        body.otp_code,
        body.approval_token,
        auth_factor=auth_factor,
    ):
        raise HTTPException(status_code=401, detail="invalid otp")

    gate.status = "rejected"
    gate.device_id = device.device_id
    run.status = "rejected"
    log_audit(
        db,
        "reject",
        run.id,
        device.device_id,
        gate.gate,
        actor=ACTOR_ANDROID,
        result=RESULT_REJECTED,
        event_metadata={"gate": gate.gate},
    )
    db.commit()
    publish_run_update(
        {
            "type": "rejection",
            "run_id": run.id,
            "status": run.status,
            "gate": gate.gate,
        }
    )
    return {"ok": True, "run_id": run.id, "status": "rejected"}


def _control(
    run_id: int,
    body: RunControlRequest,
    db: Session,
    action: str,
):
    run = _require_run(db, run_id)
    device = _require_device(db, body.device_id)
    payload = f"{device.device_id}|{run.id}|{action}"
    auth_factor = device_auth_factor(
        device,
        body.otp_code,
        None,
        None,
        payload,
    )
    if auth_factor is None:
        raise HTTPException(status_code=401, detail="invalid otp")
    if not consume_device_authorization(
        db,
        device,
        payload,
        body.otp_code,
        None,
        auth_factor=auth_factor,
    ):
        raise HTTPException(status_code=401, detail="invalid otp")

    pending_task = None
    if action == "pause":
        if run.status in TERMINAL_STATUSES:
            raise HTTPException(status_code=409, detail="run is terminal")
        if run.status == "awaiting_patch_review":
            run.pipeline_stage = STAGE_PATCH_REVIEW
        elif run.status == "awaiting_merge":
            run.pipeline_stage = STAGE_MERGE
        elif run.status in ("running", "queued") and not run.pipeline_stage:
            run.pipeline_stage = STAGE_CLONE if run.status == "running" else STAGE_PROVISION
        run.control_state = "paused"
        run.status = "paused"
    elif action == "resume":
        if run.control_state != "paused" or run.status != "paused":
            raise HTTPException(status_code=409, detail="run is not paused")
        pending_task = resume_paused_run(run, db)
    elif action == "kill":
        run.control_state = "killed"
        run.status = "killed"
        _ensure_finished_at(run)
        log_audit(
            db,
            action,
            run.id,
            device.device_id,
            action,
            actor=ACTOR_ANDROID,
            result=RESULT_SUCCESS,
            event_metadata={"control": action},
        )
        db.commit()
        try:
            _kill_sandbox(run)
        except Exception:
            logger.exception("failed to kill sandbox run_id=%s", run.id)
        publish_run_update(
            {
                "type": "control",
                "run_id": run.id,
                "status": run.status,
                "control_state": run.control_state,
            }
        )
        return {"ok": True, "run_id": run.id, "control_state": run.control_state}

    log_audit(
        db,
        action,
        run.id,
        device.device_id,
        action,
        actor=ACTOR_ANDROID,
        result=RESULT_SUCCESS,
        event_metadata={"control": action},
    )
    db.commit()
    if pending_task is not None:
        _enqueue(pending_task, run.id)
    publish_run_update(
        {
            "type": "control",
            "run_id": run.id,
            "status": run.status,
            "control_state": run.control_state,
        }
    )
    return {"ok": True, "run_id": run.id, "control_state": run.control_state}


@router.post(
    "/v1/sandbox/runs/{run_id}/pause",
    dependencies=[Depends(require_api_key)],
)
def pause_run(
    run_id: int,
    body: RunControlRequest,
    db: Session = Depends(get_db),
):
    return _control(run_id, body, db, "pause")


@router.post(
    "/v1/sandbox/runs/{run_id}/resume",
    dependencies=[Depends(require_api_key)],
)
def resume_run(
    run_id: int,
    body: RunControlRequest,
    db: Session = Depends(get_db),
):
    return _control(run_id, body, db, "resume")


@router.post(
    "/v1/sandbox/runs/{run_id}/kill",
    dependencies=[Depends(require_api_key)],
)
def kill_run(
    run_id: int,
    body: RunControlRequest,
    db: Session = Depends(get_db),
):
    return _control(run_id, body, db, "kill")


@router.get(
    "/v1/sandbox/approvals/pending",
    dependencies=[Depends(require_api_key)],
)
def list_pending_approvals(
    device_id: str,
    db: Session = Depends(get_db),
):
    _require_device(db, device_id)
    expire_stale_gates(db, notify=False, recreate=False, limit=20)
    now = datetime.now(timezone.utc)
    gates = (
        db.query(ApprovalGate, SandboxRun)
        .join(SandboxRun, ApprovalGate.run_id == SandboxRun.id)
        .filter(
            ApprovalGate.status == "pending",
            ApprovalGate.expires_at > now,
            ApprovalGate.device_id == device_id,
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
                "diff": run.current_diff,
                "expires_at": (
                    gate.expires_at.isoformat() if gate.expires_at else None
                ),
            }
            for gate, run in gates
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
    run = _require_run(db, run_id)
    return {
        "id": run.id,
        "status": run.status,
        "repo": run.repo,
        "ref": run.ref,
        "e2b_sandbox_id": run.e2b_sandbox_id,
        "duration_ms": run.duration_ms,
        "error": run.error,
        "current_diff": run.current_diff,
        "pr_url": run.pr_url,
        "control_state": run.control_state,
        "pipeline_stage": run.pipeline_stage,
        "patch_attempts": run.patch_attempts,
        "stack_trace": run.stack_trace,
        "symbol_count": (
            db.query(func.count(Symbol.id))
            .filter(Symbol.run_id == run.id)
            .scalar()
            or 0
        ),
    }


@router.get(
    "/v1/sandbox/runs/{run_id}/diagnosis",
    dependencies=[Depends(require_api_key)],
)
def get_run_diagnosis(
    run_id: int,
    db: Session = Depends(get_db),
):
    run = _require_run(db, run_id)
    event = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.run_id == run.id,
            AuditEvent.action == "diagnosis",
        )
        .order_by(AuditEvent.id.desc())
        .first()
    )
    return {
        "run_id": run.id,
        "diagnosis": event.detail if event is not None else None,
        "created_at": (
            event.created_at.isoformat()
            if event is not None and event.created_at
            else None
        ),
    }


@router.get(
    "/v1/sandbox/runs/{run_id}/logs",
    dependencies=[Depends(require_api_key)],
)
def get_run_logs(
    run_id: int,
    db: Session = Depends(get_db),
):
    _require_run(db, run_id)
    chunks: list[dict] = []
    repros = (
        db.query(ReproductionAttempt)
        .filter(ReproductionAttempt.run_id == run_id)
        .order_by(ReproductionAttempt.id.asc())
        .all()
    )
    patches = (
        db.query(PatchAttempt)
        .filter(PatchAttempt.run_id == run_id)
        .order_by(PatchAttempt.id.asc())
        .all()
    )
    for attempt in repros:
        if attempt.stdout:
            chunks.append(
                {
                    "stream": "stdout",
                    "chunk": sanitize_log_text(attempt.stdout),
                    "source": "reproduction",
                    "id": attempt.id,
                }
            )
        if attempt.stderr:
            chunks.append(
                {
                    "stream": "stderr",
                    "chunk": sanitize_log_text(attempt.stderr),
                    "source": "reproduction",
                    "id": attempt.id,
                }
            )
    for record in patches:
        if record.stdout:
            chunks.append(
                {
                    "stream": "stdout",
                    "chunk": sanitize_log_text(record.stdout),
                    "source": "verify",
                    "id": record.id,
                }
            )
        if record.stderr:
            chunks.append(
                {
                    "stream": "stderr",
                    "chunk": sanitize_log_text(record.stderr),
                    "source": "verify",
                    "id": record.id,
                }
            )
    return {"chunks": chunks}


@router.get(
    "/v1/sandbox/runs/{run_id}/audit",
    dependencies=[Depends(require_api_key)],
)
def list_audit(run_id: int, db: Session = Depends(get_db)):
    _require_run(db, run_id)
    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.run_id == run_id)
        .order_by(AuditEvent.id.desc())
        .all()
    )
    return {
        "events": [
            {
                "id": event.id,
                "action": event.action,
                "device_id": event.device_id,
                "detail": event.detail,
                "actor": event.actor,
                "result": event.result,
                "metadata": event.event_metadata,
                "created_at": event.created_at.isoformat()
                if event.created_at
                else None,
            }
            for event in events
        ]
    }


@router.get(
    "/v1/sandbox/audit",
    dependencies=[Depends(require_api_key)],
)
def list_recent_audit(
    limit: int = 100,
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 500))
    events = (
        db.query(AuditEvent)
        .order_by(AuditEvent.id.desc())
        .limit(limit)
        .all()
    )
    run_ids = [event.run_id for event in events if event.run_id is not None]
    runs_by_id: dict[int, SandboxRun] = {}
    if run_ids:
        for run in db.query(SandboxRun).filter(SandboxRun.id.in_(run_ids)).all():
            runs_by_id[run.id] = run
    return {
        "events": [
            {
                "id": event.id,
                "run_id": event.run_id,
                "repository": (
                    runs_by_id[event.run_id].repo
                    if event.run_id is not None and event.run_id in runs_by_id
                    else None
                ),
                "action": event.action,
                "device_id": event.device_id,
                "detail": event.detail,
                "actor": event.actor,
                "result": event.result,
                "metadata": event.event_metadata,
                "created_at": (
                    event.created_at.isoformat() if event.created_at else None
                ),
            }
            for event in events
        ]
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
        .options(
            noload(SandboxRun.symbols),
            noload(SandboxRun.approval_gates),
            noload(SandboxRun.reproduction_attempts),
            noload(SandboxRun.patch_records),
            noload(SandboxRun.audit_events),
        )
        .order_by(SandboxRun.id.desc())
        .limit(limit)
        .all()
    )
    run_ids = [run.id for run in runs]
    symbol_counts = dict(
        db.query(Symbol.run_id, func.count(Symbol.id))
        .filter(Symbol.run_id.in_(run_ids))
        .group_by(Symbol.run_id)
        .all()
    ) if run_ids else {}
    stats = (
        db.query(
            func.count(SandboxRun.id).label("total"),
            func.count(SandboxRun.id)
            .filter(
                SandboxRun.status == "completed",
                SandboxRun.pr_url.isnot(None),
            )
            .label("successful"),
            func.count(SandboxRun.id)
            .filter(SandboxRun.status.in_(["running", "queued"]))
            .label("running"),
            func.count(SandboxRun.id)
            .filter(SandboxRun.status.in_(["failed", "killed", "rejected"]))
            .label("failed"),
        )
        .one()
    )
    return {
        "stats": {
            "total": stats.total or 0,
            "successful": stats.successful or 0,
            "running": stats.running or 0,
            "failed": stats.failed or 0,
        },
        "runs": [
            {
                "id": run.id,
                "repo": run.repo,
                "ref": run.ref,
                "status": run.status,
                "duration_ms": run.duration_ms,
                "error": run.error,
                "current_diff": run.current_diff,
                "pr_url": run.pr_url,
                "control_state": run.control_state,
                "pipeline_stage": run.pipeline_stage,
                "patch_attempts": run.patch_attempts,
                "started_at": (
                    run.started_at.isoformat() if run.started_at else None
                ),
                "finished_at": (
                    run.finished_at.isoformat() if run.finished_at else None
                ),
                "symbol_count": symbol_counts.get(run.id, 0),
            }
            for run in runs
        ],
    }


@router.get(
    "/v1/ws/ticket",
    dependencies=[Depends(require_api_key)],
)
def websocket_ticket():
    ticket, expires_in = issue_ws_ticket()
    return {"ticket": ticket, "expires_in": expires_in}


@router.websocket("/v1/ws/runs")
async def runs_socket(websocket: WebSocket):
    header_key = websocket.headers.get("x-api-key")
    ticket = ticket_from_ws_protocols(
        websocket.headers.get("sec-websocket-protocol")
    )
    accept_subprotocol: str | None = None
    if ticket and verify_ws_ticket(ticket):
        accept_subprotocol = ws_subprotocol_for_ticket(ticket)
    elif ws_api_key_header_allowed() and secrets_match(
        header_key, settings.api_key
    ):
        pass
    else:
        await websocket.close(code=1008)
        return
    if accept_subprotocol:
        await websocket.accept(subprotocol=accept_subprotocol)
    else:
        await websocket.accept()
    from app.db import SessionLocal
    from app.services.events import subscribe_run_updates

    async def send_snapshot(event=None):
        db = SessionLocal()
        try:
            runs = (
                db.query(SandboxRun)
                .order_by(SandboxRun.id.desc())
                .limit(20)
                .all()
            )
            payload = serialize_runs(runs)
            if event is not None:
                payload["event"] = event
            await websocket.send_json(payload)
        finally:
            db.close()

    try:
        await send_snapshot()
        async for message in subscribe_run_updates():
            event = None
            raw = message.get("data")
            if raw:
                try:
                    event = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    event = None
            if isinstance(event, dict) and event.get("type") == "agent_log":
                await websocket.send_json({"event": event})
            else:
                await send_snapshot(event)
    except WebSocketDisconnect:
        return
