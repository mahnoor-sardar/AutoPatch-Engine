import pytest

from app.config import settings
from app.db import SessionLocal
from app.models import Device
from app.workers import tasks as worker_tasks

TEST_APPROVAL_DEVICE_ID = "dev-1"
TEST_APPROVAL_TOTP_SECRET = "JBSWY3DPEHPK3PXP"


def _ensure_bindable_test_approval_device() -> None:
    db = SessionLocal()
    try:
        device = (
            db.query(Device)
            .filter(Device.device_id == TEST_APPROVAL_DEVICE_ID)
            .one_or_none()
        )
        if device is None:
            db.add(
                Device(
                    device_id=TEST_APPROVAL_DEVICE_ID,
                    fcm_token="test-fcm",
                    totp_secret=TEST_APPROVAL_TOTP_SECRET,
                    label="test-approval",
                    revoked_at=None,
                )
            )
        else:
            device.totp_secret = TEST_APPROVAL_TOTP_SECRET
            device.revoked_at = None
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _default_patch_pipeline_flags(monkeypatch):
    """Keep the patch state machine on unless a test opts into the audit stop."""
    monkeypatch.setattr(settings, "autopatch_stop_after_repro", False)
    monkeypatch.setattr(
        worker_tasks,
        "diagnose_reproduction",
        lambda **kwargs: "test diagnosis",
    )


@pytest.fixture(autouse=True)
def _default_approval_device(monkeypatch):
    """Give gate-creating tests a bindable approval device.

    pytest restores ``settings.approval_device_id`` after the test, so an
    explicit ``monkeypatch.setattr(..., None)`` still wins for that test.
    """
    monkeypatch.setattr(settings, "approval_device_id", TEST_APPROVAL_DEVICE_ID)
    _ensure_bindable_test_approval_device()
