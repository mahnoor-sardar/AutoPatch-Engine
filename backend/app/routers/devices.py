from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.db import get_db
from app.models import Device, PushEvent
from app.schemas import DeviceRegister
from app.services import fcm

router = APIRouter()


@router.post(
    "/v1/devices/register",
    dependencies=[Depends(require_api_key)],
)
def register_device(body: DeviceRegister, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.device_id == body.device_id).one_or_none()
    if device is None:
        device = Device(device_id=body.device_id, fcm_token=body.fcm_token, label=body.label)
        db.add(device)
    else:
        device.fcm_token = body.fcm_token
        device.label = body.label
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
