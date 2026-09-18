from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
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


class ApprovalDeviceUnavailable(Exception):
    def __init__(self, detail: str = "approval device is not available") -> None:
        self.detail = detail
        super().__init__(detail)


def resolve_approval_device(db: Session) -> Device:
    configured = (settings.approval_device_id or "").strip()
    if not configured:
        raise ApprovalDeviceUnavailable("approval device is not configured")
    return load_bindable_device(db, configured)


def load_bindable_device(db: Session, device_id: str) -> Device:
    device = (
        db.query(Device)
        .filter(Device.device_id == device_id)
        .one_or_none()
    )
    if device is None or not device.totp_secret:
        raise ApprovalDeviceUnavailable("approval device is not available")
    if device.revoked_at is not None:
        raise ApprovalDeviceUnavailable("approval device is revoked")
    return device


def create_pending_gate(
    db: Session,
    run: SandboxRun,
    gate_name: str,
    notify: bool = True,
    device_id: str | None = None,
) -> ApprovalGate:
    if device_id:
        device = load_bindable_device(db, device_id)
    else:
        device = resolve_approval_device(db)
    gate = ApprovalGate(
        run_id=run.id,
        gate=gate_name,
        status="pending",
        device_id=device.device_id,
        expires_at=datetime.now(timezone.utc)
        + timedelta(seconds=GATE_TTL_SECONDS),
    )
    db.add(gate)
    db.commit()
    db.refresh(gate)
    if notify:
        notify_devices_of_approval_gate(db, run, gate)
    return gate


def try_claim_pending_gate(
    db: Session,
    gate_id: int,
    device_id: str,
) -> ApprovalGate | None:
    """Atomically move a gate from pending to approved.

    Returns the gate when this caller won the claim. Returns None if the
    gate is missing or already left pending (replay / lost race).
    Rejects callers that are not the gate's bound device.
    """
    query = db.query(ApprovalGate).filter(
        ApprovalGate.id == gate_id,
        ApprovalGate.status == "pending",
    )
    if hasattr(query, "with_for_update"):
        query = query.with_for_update()
    locked = query.one_or_none()
    if locked is None:
        return None
    if not locked.device_id or locked.device_id != device_id:
        raise HTTPException(
            status_code=403,
            detail="device is not authorized for this gate",
        )
    locked.status = "approved"
    locked.approved_at = datetime.now(timezone.utc)
    return locked


def create_pending_provision_gate(
    db: Session,
    run: SandboxRun,
) -> ApprovalGate:
    return create_pending_gate(db, run, SANDBOX_PROVISION_GATE, notify=False)


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

    if not gate.device_id:
        db.commit()
        return
    device = (
        db.query(Device)
        .filter(
            Device.device_id == gate.device_id,
            Device.revoked_at.is_(None),
        )
        .one_or_none()
    )
    if device is None or not device.totp_secret:
        db.commit()
        return
    status = "sent"
    try:
        fcm.send_push_with_timeout(device.fcm_token, title, body, data)
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


def expire_stale_gates(
    db: Session,
    *,
    notify: bool = True,
    recreate: bool = False,
    limit: int | None = None,
) -> list[ApprovalGate]:
    now = datetime.now(timezone.utc)
    query = (
        db.query(ApprovalGate)
        .filter(
            ApprovalGate.status == "pending",
            ApprovalGate.expires_at.isnot(None),
            ApprovalGate.expires_at <= now,
        )
        .order_by(ApprovalGate.id.desc())
    )
    if limit is not None:
        query = query.limit(limit)
    pending = list(query.all())
    expired: list[ApprovalGate] = []
    for gate in pending:
        if not gate_is_expired(gate):
            continue
        apply_gate_expiry(db, gate, recreate=recreate, notify=notify)
        expired.append(gate)
    return expired


def apply_gate_expiry(
    db: Session,
    gate: ApprovalGate,
    recreate: bool = True,
    notify: bool = True,
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
        if notify:
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
            if not gate.device_id:
                db.commit()
                return
            try:
                create_pending_gate(
                    db,
                    run,
                    gate.gate,
                    notify=notify,
                    device_id=gate.device_id,
                )
            except ApprovalDeviceUnavailable:
                db.commit()
            return
    db.commit()
