from datetime import datetime, timezone
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, noload

from app.auth import require_api_key
from app.config import settings
from app.db import get_db
from app.models import ApprovalGate, AuditEvent, Device, Repository, SandboxRun, Symbol
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
    apply_gate_expiry,
    create_pending_gate,
    create_pending_provision_gate,
    expire_stale_gates,
    gate_is_expired,
)
from app.services.audit import (
    ACTOR_ANDROID,
    RESULT_REJECTED,
    RESULT_SUCCESS,
    log_audit,
    verify_device_authorization,
)
from app.services.events import publish_run_update
from app.services.providers import get_sandbox_provider
from app.workers.tasks import apply_patch_and_verify, clone_and_index, open_github_pr

router = APIRouter()
logger = logging.getLogger(__name__)


def _enqueue(task, run_id: int) -> None:
    result = task.delay(run_id)
    logger.info(
        "published celery task %s run_id=%s task_id=%s queue=celery",
        getattr(task, "name", task),
        run_id,
        getattr(result, "id", None),
    )


def _enqueue_for_gate(gate_name: str, run_id: int) -> None:
    if gate_name == SANDBOX_PROVISION_GATE:
        _enqueue(clone_and_index, run_id)
    elif gate_name == PATCH_REVIEW_GATE:
        _enqueue(apply_patch_and_verify, run_id)
    elif gate_name == MERGE_GATE:
        _enqueue(open_github_pr, run_id)


def _require_device(db: Session, device_id: str) -> Device:
    device = (
        db.query(Device)
        .filter(Device.device_id == device_id)
        .one_or_none()
    )
    if device is None or not device.totp_secret:
        raise HTTPException(status_code=404, detail="device not registered")
    return device


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
                "status": run.status,
                "current_diff": run.current_diff,
                "pr_url": run.pr_url,
                "control_state": run.control_state,
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
    create_pending_gate(db, run, name)


def resume_paused_run(run: SandboxRun, db: Session) -> None:
    run.control_state = "active"
    stage = run.pipeline_stage or STAGE_PROVISION
    if stage == STAGE_PROVISION:
        run.status = "queued"
        gate = _latest_gate(db, run, SANDBOX_PROVISION_GATE)
        if gate is not None and gate.status == "approved":
            _enqueue(clone_and_index, run.id)
            return
        _ensure_pending_gate(db, run, SANDBOX_PROVISION_GATE)
        return
    if stage == STAGE_CLONE:
        run.status = "queued"
        _enqueue(clone_and_index, run.id)
        return
    if stage == STAGE_PATCH_REVIEW:
        run.status = "awaiting_patch_review"
        gate = _latest_gate(db, run, PATCH_REVIEW_GATE)
        if gate is not None and gate.status == "approved":
            _enqueue(apply_patch_and_verify, run.id)
            return
        _ensure_pending_gate(db, run, PATCH_REVIEW_GATE)
        return
    if stage == STAGE_PATCH_APPLY:
        run.status = "queued"
        _enqueue(apply_patch_and_verify, run.id)
        return
    if stage == STAGE_MERGE:
        run.status = "awaiting_merge"
        gate = _latest_gate(db, run, MERGE_GATE)
        if gate is not None and gate.status == "approved":
            _enqueue(open_github_pr, run.id)
            return
        _ensure_pending_gate(db, run, MERGE_GATE)
        return
    if stage == STAGE_PR:
        run.status = "queued"
        _enqueue(open_github_pr, run.id)
        return
    run.status = "queued"
    _enqueue(clone_and_index, run.id)


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
    gate = create_pending_provision_gate(db, run)
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
            _unpause_on_approve(run)
            db.commit()
            _enqueue_for_gate(latest.gate, run.id)
            return {
                "ok": True,
                "run_id": run.id,
                "gate": latest.gate,
                "status": latest.status,
            }
        raise HTTPException(status_code=404, detail="approval gate not found")

    _expire_if_needed(db, gate)
    device = _require_device(db, body.device_id)
    payload = f"{device.device_id}|{run.id}|{gate.gate}"
    if not verify_device_authorization(
        device,
        body.otp_code,
        body.approval_token,
        body.token_ts,
        payload,
    ):
        raise HTTPException(status_code=401, detail="invalid otp")

    _unpause_on_approve(run)
    gate.status = "approved"
    gate.device_id = device.device_id
    gate.approved_at = datetime.now(timezone.utc)
    if run.status in ("paused",):
        run.status = "queued"
    log_audit(
        db,
        "approve",
        run.id,
        device.device_id,
        gate.gate,
        actor=ACTOR_ANDROID,
        result=RESULT_SUCCESS,
        event_metadata={"gate": gate.gate},
    )
    db.commit()
    _enqueue_for_gate(gate.gate, run.id)
    publish_run_update(
        {
            "type": "approval",
            "run_id": run.id,
            "status": run.status,
            "gate": gate.gate,
            "gate_status": gate.status,
        }
    )
    return {
        "ok": True,
        "run_id": run.id,
        "gate": gate.gate,
        "status": gate.status,
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
            return {"ok": True, "run_id": run.id, "status": "rejected"}
        raise HTTPException(status_code=404, detail="approval gate not found")
    _expire_if_needed(db, gate)
    device = _require_device(db, body.device_id)
    payload = f"{device.device_id}|{run.id}|{gate.gate}"
    if not verify_device_authorization(
        device,
        body.otp_code,
        body.approval_token,
        body.token_ts,
        payload,
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
    if not verify_device_authorization(
        device,
        body.otp_code,
        None,
        None,
        payload,
    ):
        raise HTTPException(status_code=401, detail="invalid otp")

    if action == "pause":
        if run.status == "awaiting_patch_review":
            run.pipeline_stage = STAGE_PATCH_REVIEW
        elif run.status == "awaiting_merge":
            run.pipeline_stage = STAGE_MERGE
        elif run.status in ("running", "queued") and not run.pipeline_stage:
            run.pipeline_stage = STAGE_CLONE if run.status == "running" else STAGE_PROVISION
        run.control_state = "paused"
        run.status = "paused"
    elif action == "resume":
        if run.control_state != "paused":
            raise HTTPException(status_code=409, detail="run is not paused")
        resume_paused_run(run, db)
    elif action == "kill":
        run.control_state = "killed"
        run.status = "killed"
        _kill_sandbox(run)

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
    expire_stale_gates(db, notify=False, recreate=False, limit=20)
    now = datetime.now(timezone.utc)
    gates = (
        db.query(ApprovalGate, SandboxRun)
        .join(SandboxRun, ApprovalGate.run_id == SandboxRun.id)
        .filter(
            ApprovalGate.status == "pending",
            ApprovalGate.expires_at > now,
            or_(
                ApprovalGate.device_id.is_(None),
                ApprovalGate.device_id == device_id,
            ),
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
            .filter(SandboxRun.status == "completed")
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


@router.websocket("/v1/ws/runs")
async def runs_socket(websocket: WebSocket):
    api_key = websocket.query_params.get("api_key")
    if not api_key or api_key != settings.api_key:
        await websocket.close(code=1008)
        return
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
            await send_snapshot(event)
    except WebSocketDisconnect:
        return
