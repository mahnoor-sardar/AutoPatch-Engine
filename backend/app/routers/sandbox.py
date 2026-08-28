from datetime import datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.config import settings
from app.db import get_db
from app.models import ApprovalGate, AuditEvent, Device, Repository, SandboxRun
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
from app.services.audit import log_audit, verify_device_authorization
from app.services.events import publish_run_update
from app.services.providers import get_sandbox_provider
from app.workers.tasks import apply_patch_and_verify, clone_and_index, open_github_pr

router = APIRouter()


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
        apply_gate_expiry(db, gate, recreate=True)
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
            clone_and_index.delay(run.id)
            return
        _ensure_pending_gate(db, run, SANDBOX_PROVISION_GATE)
        return
    if stage == STAGE_CLONE:
        run.status = "queued"
        clone_and_index.delay(run.id)
        return
    if stage == STAGE_PATCH_REVIEW:
        run.status = "awaiting_patch_review"
        gate = _latest_gate(db, run, PATCH_REVIEW_GATE)
        if gate is not None and gate.status == "approved":
            apply_patch_and_verify.delay(run.id)
            return
        _ensure_pending_gate(db, run, PATCH_REVIEW_GATE)
        return
    if stage == STAGE_PATCH_APPLY:
        run.status = "queued"
        apply_patch_and_verify.delay(run.id)
        return
    if stage == STAGE_MERGE:
        run.status = "awaiting_merge"
        gate = _latest_gate(db, run, MERGE_GATE)
        if gate is not None and gate.status == "approved":
            open_github_pr.delay(run.id)
            return
        _ensure_pending_gate(db, run, MERGE_GATE)
        return
    if stage == STAGE_PR:
        run.status = "queued"
        open_github_pr.delay(run.id)
        return
    run.status = "queued"
    clone_and_index.delay(run.id)


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
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    create_pending_provision_gate(db, run)
    return {"id": run.id, "status": run.status}


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
    gate = _pending_gate(db, run)
    if gate is None:
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

    if run.control_state == "killed":
        raise HTTPException(status_code=409, detail="run was killed")

    _unpause_on_approve(run)
    gate.status = "approved"
    gate.device_id = device.device_id
    gate.approved_at = datetime.now(timezone.utc)
    db.commit()
    log_audit(db, "approve", run.id, device.device_id, gate.gate)

    if gate.gate == SANDBOX_PROVISION_GATE:
        clone_and_index.delay(run.id)
    elif gate.gate == PATCH_REVIEW_GATE:
        apply_patch_and_verify.delay(run.id)
    elif gate.gate == MERGE_GATE:
        open_github_pr.delay(run.id)

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
    db.commit()
    log_audit(db, "reject", run.id, device.device_id, gate.gate)
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

    db.commit()
    log_audit(db, action, run.id, device.device_id, action)
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
    expire_stale_gates(db)
    gates = (
        db.query(ApprovalGate, SandboxRun)
        .join(SandboxRun, ApprovalGate.run_id == SandboxRun.id)
        .filter(
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
                "diff": run.current_diff,
                "expires_at": (
                    gate.expires_at.isoformat() if gate.expires_at else None
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
        "symbol_count": len(run.symbols),
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
                "symbol_count": len(run.symbols),
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
