from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import ApprovalGate, Device, PushEvent, SandboxRun
from app.services import fcm
from app.services.audit import (
    ACTOR_SYSTEM,
    RESULT_EXPIRED,
    log_audit,
)

SANDBOX_PROVISION_GATE = "sandbox_provision"
PATCH_REVIEW_GATE = "patch_review"
MERGE_GATE = "merge"
GATE_TTL_SECONDS = 90

STAGE_PROVISION = "provision"
STAGE_CLONE = "clone"
STAGE_PATCH_REVIEW = "patch_review"
STAGE_PATCH_APPLY = "patch_apply"
STAGE_MERGE = "merge"
STAGE_PR = "pr"


def create_pending_gate(
    db: Session,
    run: SandboxRun,
    gate_name: str,
) -> ApprovalGate:
    gate = ApprovalGate(
        run_id=run.id,
        gate=gate_name,
        status="pending",
        expires_at=datetime.now(timezone.utc)
        + timedelta(seconds=GATE_TTL_SECONDS),
    )
    db.add(gate)
    db.commit()
    db.refresh(gate)
    notify_devices_of_approval_gate(db, run, gate)
    return gate


def create_pending_provision_gate(
    db: Session,
    run: SandboxRun,
) -> ApprovalGate:
    return create_pending_gate(db, run, SANDBOX_PROVISION_GATE)


def notify_devices_of_approval_gate(
    db: Session,
    run: SandboxRun,
    gate: ApprovalGate,
) -> None:
    title = "Approval required"
    body = f"{run.repo} is waiting for {gate.gate} approval."
    expires_at = gate.expires_at.isoformat() if gate.expires_at else ""
    data = {
        "run_id": str(run.id),
        "gate": gate.gate,
        "repository": run.repo,
        "expires_at": expires_at,
    }
    if run.current_diff:
        data["has_diff"] = "true"

    for device in db.query(Device).all():
        status = "sent"
        try:
            fcm.send_push(device.fcm_token, title, body, data)
        except Exception:
            status = "failed"
        db.add(
            PushEvent(
                device_id=device.device_id,
                title=title,
                status=status,
            )
        )
    db.commit()


def gate_is_expired(gate: ApprovalGate, now: datetime | None = None) -> bool:
    if gate.expires_at is None:
        return False
    moment = now or datetime.now(timezone.utc)
    expires = gate.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires <= moment


def expire_stale_gates(db: Session) -> list[ApprovalGate]:
    pending = list(
        db.query(ApprovalGate)
        .filter(ApprovalGate.status == "pending")
        .all()
    )
    expired: list[ApprovalGate] = []
    for gate in pending:
        if gate_is_expired(gate):
            apply_gate_expiry(db, gate, recreate=True)
            expired.append(gate)
    return expired


def apply_gate_expiry(
    db: Session,
    gate: ApprovalGate,
    recreate: bool = True,
) -> None:
    if gate.status != "pending":
        return
    gate.status = "expired"
    run = (
        db.query(SandboxRun)
        .filter(SandboxRun.id == gate.run_id)
        .one_or_none()
    )
    if run is not None and run.control_state != "killed":
        run.control_state = "paused"
        run.status = "paused"
        log_audit(
            db,
            "expire",
            run.id,
            None,
            gate.gate,
            actor=ACTOR_SYSTEM,
            result=RESULT_EXPIRED,
            event_metadata={"gate": gate.gate},
        )
        from app.services.events import notify_run_event

        notify_run_event(
            db,
            run,
            "Approval expired — run paused",
            f"{run.repo} {gate.gate} timed out. Re-approval required.",
            {
                "escalation": "true",
                "gate": gate.gate,
                "expired": "true",
            },
        )
        if recreate:
            create_pending_gate(db, run, gate.gate)
            return
    db.commit()
