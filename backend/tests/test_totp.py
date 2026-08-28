import time

import pyotp
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Device
from app.services.audit import make_approval_token, verify_device_authorization
from app.services.totp import new_secret, provisioning_uri, verify_code


client = TestClient(app)
HEADERS = {"X-API-Key": "dev-local-key"}


def test_totp_roundtrip():
    secret = new_secret()
    code = pyotp.TOTP(secret).now()
    assert verify_code(secret, code)
    assert not verify_code(secret, "000000")


def test_totp_verify_rejects_empty_and_wrong_secret():
    secret = new_secret()
    code = pyotp.TOTP(secret).now()
    assert not verify_code("", code)
    assert not verify_code(secret, "")
    assert not verify_code(secret, "abcdef")
    other = new_secret()
    assert not verify_code(other, code)


def test_totp_verify_accepts_adjacent_window():
    secret = new_secret()
    totp = pyotp.TOTP(secret)
    prev_code = totp.at(int(time.time()) - 30)
    assert verify_code(secret, prev_code)


def test_provisioning_uri_contains_device():
    secret = new_secret()
    uri = provisioning_uri(secret, "android-device-1")
    assert uri.startswith("otpauth://totp/")
    assert "android-device-1" in uri
    assert "AutoPatch" in uri
    assert secret in uri


def test_signed_approval_token():
    secret = new_secret()
    device = Device(
        device_id="dev-1",
        fcm_token="token",
        totp_secret=secret,
    )
    ts = int(time.time())
    payload = "dev-1|9|sandbox_provision"
    token = make_approval_token(secret, payload, ts)
    assert verify_device_authorization(
        device,
        otp_code=None,
        approval_token=token,
        token_ts=ts,
        payload=payload,
    )
    assert not verify_device_authorization(
        device,
        otp_code=None,
        approval_token="deadbeef",
        token_ts=ts,
        payload=payload,
    )


def test_dev_totp_setup_requires_api_key():
    response = client.get("/v1/devices/x/dev/totp-setup")
    assert response.status_code == 401


def test_dev_totp_setup_hidden_outside_dev_env(monkeypatch):
    monkeypatch.setattr("app.services.totp.settings.app_env", "production")
    response = client.get(
        "/v1/devices/any/dev/totp-setup",
        headers=HEADERS,
    )
    assert response.status_code == 404
    body = response.json()
    assert "secret" not in body
    assert "otpauth_url" not in body


def test_dev_totp_setup_returns_existing_device(monkeypatch):
    monkeypatch.setattr("app.services.totp.settings.app_env", "local")
    secret = new_secret()
    device_id = "totp-setup-test-device"
    db = SessionLocal()
    try:
        device = (
            db.query(Device)
            .filter(Device.device_id == device_id)
            .one_or_none()
        )
        if device is None:
            device = Device(
                device_id=device_id,
                fcm_token="test-token",
                totp_secret=secret,
                label="dev",
            )
            db.add(device)
        else:
            device.totp_secret = secret
        db.commit()
    finally:
        db.close()

    response = client.get(
        f"/v1/devices/{device_id}/dev/totp-setup",
        headers=HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dev_only"] is True
    assert body["device_id"] == device_id
    assert body["secret"] == secret
    assert body["otpauth_url"].startswith("otpauth://totp/")
    assert device_id in body["otpauth_url"]
    assert verify_code(body["secret"], pyotp.TOTP(body["secret"]).now())


def test_dev_totp_rotate_requires_api_key():
    response = client.post("/v1/devices/x/dev/totp-rotate")
    assert response.status_code == 401


def test_dev_totp_rotate_hidden_outside_dev_env(monkeypatch):
    monkeypatch.setattr("app.services.totp.settings.app_env", "production")
    response = client.post(
        "/v1/devices/any/dev/totp-rotate",
        headers=HEADERS,
    )
    assert response.status_code == 404
    body = response.json()
    assert "secret" not in body
    assert "otpauth_url" not in body


def test_dev_totp_rotate_replaces_existing_secret(monkeypatch):
    monkeypatch.setattr("app.services.totp.settings.app_env", "local")
    old_secret = new_secret()
    device_id = "totp-rotate-test-device"
    db = SessionLocal()
    try:
        device = (
            db.query(Device)
            .filter(Device.device_id == device_id)
            .one_or_none()
        )
        if device is None:
            device = Device(
                device_id=device_id,
                fcm_token="test-token",
                totp_secret=old_secret,
                label="dev",
            )
            db.add(device)
        else:
            device.totp_secret = old_secret
        db.commit()
    finally:
        db.close()

    response = client.post(
        f"/v1/devices/{device_id}/dev/totp-rotate",
        headers=HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dev_only"] is True
    assert body["rotated"] is True
    assert body["device_id"] == device_id
    assert body["secret"] != old_secret
    assert body["otpauth_url"].startswith("otpauth://totp/")
    assert body["secret"] in body["otpauth_url"]
    assert verify_code(body["secret"], pyotp.TOTP(body["secret"]).now())
    assert not verify_code(old_secret, pyotp.TOTP(body["secret"]).now())

    db = SessionLocal()
    try:
        stored = (
            db.query(Device)
            .filter(Device.device_id == device_id)
            .one()
        )
        assert stored.totp_secret == body["secret"]
        assert stored.totp_secret != old_secret
    finally:
        db.close()
