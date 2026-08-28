from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.db import get_db
from app.models import Device, PushEvent
from app.schemas import DeviceRegister
from app.services import fcm, totp

router = APIRouter()


@router.post(
    "/v1/devices/register",
    dependencies=[Depends(require_api_key)],
)
def register_device(body: DeviceRegister, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.device_id == body.device_id).one_or_none()
    if device is None:
        device = Device(
            device_id=body.device_id,
            fcm_token=body.fcm_token,
            label=body.label,
            totp_secret=totp.new_secret(),
        )
        db.add(device)
    else:
        device.fcm_token = body.fcm_token
        device.label = body.label
        if not device.totp_secret:
            device.totp_secret = totp.new_secret()
    db.commit()
    # totp_secret is returned once for on-device encrypted storage.
    # Do not log this body. Production Android UI must not display it.
    return {
        "ok": True,
        "device_id": device.device_id,
        "totp_secret": device.totp_secret,
    }


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
    dependencies=[Depends(require_api_key)],
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
    dependencies=[Depends(require_api_key)],
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
