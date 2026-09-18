from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_api_key, require_device_enrollment
from app.db import get_db
from app.models import Device, PushEvent
from app.schemas import DeviceRegister
from app.services import fcm, totp
from app.services.audit import (
    ACTOR_ANDROID,
    ACTOR_HUMAN,
    RESULT_SUCCESS,
    log_audit,
)

router = APIRouter()


@router.post(
    "/v1/devices/register",
    dependencies=[
        Depends(require_api_key),
        Depends(require_device_enrollment),
    ],
)
def register_device(body: DeviceRegister, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.device_id == body.device_id).one_or_none()
    issued_secret: str | None = None
    if device is not None and device.revoked_at is not None:
        raise HTTPException(status_code=403, detail="device revoked")
    if device is None:
        issued_secret = totp.new_secret()
        device = Device(
            device_id=body.device_id,
            fcm_token=body.fcm_token,
            label=body.label,
            totp_secret=issued_secret,
        )
        db.add(device)
    else:
        device.fcm_token = body.fcm_token
        device.label = body.label
        if not device.totp_secret:
            issued_secret = totp.new_secret()
            device.totp_secret = issued_secret
    log_audit(
        db,
        "device_register",
        None,
        device.device_id,
        "enrolled" if issued_secret else "updated",
        actor=ACTOR_ANDROID,
        result=RESULT_SUCCESS,
        event_metadata={"secret_issued": bool(issued_secret)},
    )
    db.commit()
    # totp_secret is returned once, only for a newly issued secret.
    # Re-registration must not disclose an existing device TOTP.
    # Do not log this body. Production Android UI must not display it.
    payload = {
        "ok": True,
        "device_id": device.device_id,
    }
    if issued_secret:
        payload["totp_secret"] = issued_secret
    return payload


@router.post(
    "/v1/devices/{device_id}/revoke",
    dependencies=[Depends(require_api_key)],
)
def revoke_device(device_id: str, db: Session = Depends(get_db)):
    device = (
        db.query(Device)
        .filter(Device.device_id == device_id)
        .one_or_none()
    )
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")
    if device.revoked_at is None:
        device.revoked_at = datetime.now(timezone.utc)
    log_audit(
        db,
        "device_revoke",
        None,
        device.device_id,
        None,
        actor=ACTOR_HUMAN,
        result=RESULT_SUCCESS,
        event_metadata={},
    )
    db.commit()
    return {"ok": True, "device_id": device.device_id}


@router.post(
    "/v1/devices/{device_id}/test-push",
    dependencies=[Depends(require_api_key)],
)
def test_push(device_id: str, db: Session = Depends(get_db)):
    device = (
        db.query(Device)
        .filter(Device.device_id == device_id)
        .one_or_none()
    )

    if device is None:
        raise HTTPException(
            status_code=404,
            detail="device not found",
        )
    if device.revoked_at is not None:
        raise HTTPException(status_code=403, detail="device revoked")

    title = "AutoPatch test"
    status = "sent"

    try:
        fcm.send_push(
            device.fcm_token,
            title,
            "Device registration pipeline is working.",
        )
    except Exception as exc:
        status = "failed"
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    finally:
        db.add(
            PushEvent(
                device_id=device_id,
                title=title,
                status=status,
            )
        )
        db.commit()

    return {
        "ok": True,
        "status": status,
    }


def _require_dev_totp_device(db: Session, device_id: str) -> Device:
    if not totp.totp_setup_enabled():
        raise HTTPException(status_code=404, detail="not found")
    device = (
        db.query(Device)
        .filter(Device.device_id == device_id)
        .one_or_none()
    )
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")
    return device


@router.get(
    "/v1/devices/{device_id}/dev/totp-setup",
    dependencies=[
        Depends(require_api_key),
        Depends(require_device_enrollment),
    ],
)
def dev_totp_setup(device_id: str, db: Session = Depends(get_db)):
    """DEV/TEST only. Hidden unless APP_ENV is local/dev/test.

    Lets a developer recover otpauth setup for an already-registered device.
    Do not enable this in production. The secret is not logged.
    """
    device = _require_dev_totp_device(db, device_id)
    if not device.totp_secret:
        raise HTTPException(status_code=404, detail="device not found")

    uri = totp.provisioning_uri(device.totp_secret, device.device_id)
    return {
        "dev_only": True,
        "device_id": device.device_id,
        "issuer": totp.ISSUER,
        "otpauth_url": uri,
        "secret": device.totp_secret,
    }


@router.post(
    "/v1/devices/{device_id}/dev/totp-rotate",
    dependencies=[
        Depends(require_api_key),
        Depends(require_device_enrollment),
    ],
)
def dev_totp_rotate(device_id: str, db: Session = Depends(get_db)):
    """DEV/TEST only. Replace an existing device TOTP secret.

    Hidden unless APP_ENV is local/dev/test. The new secret is returned in
    this response only and is never logged. Approval verification is unchanged.
    """
    device = _require_dev_totp_device(db, device_id)
    device.totp_secret = totp.new_secret()
    db.commit()
    uri = totp.provisioning_uri(device.totp_secret, device.device_id)
    return {
        "dev_only": True,
        "rotated": True,
        "device_id": device.device_id,
        "issuer": totp.ISSUER,
        "otpauth_url": uri,
        "secret": device.totp_secret,
    }
