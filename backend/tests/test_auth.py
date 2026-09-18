from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def test_github_repos_requires_api_key():
    response = client.get(
        "/v1/github/repos",
        params={"installation_id": 123},
    )

    assert response.status_code == 401


def test_sandbox_runs_requires_api_key():
    response = client.get("/v1/sandbox/runs")

    assert response.status_code == 401


def test_device_register_requires_api_key():
    response = client.post(
        "/v1/devices/register",
        json={
            "device_id": "test-device",
            "fcm_token": "test-token",
            "label": "test",
        },
    )

    assert response.status_code == 401


def test_device_register_api_key_alone_is_not_enrollment(monkeypatch):
    monkeypatch.setattr(
        settings,
        "device_enrollment_secret",
        "dev-enrollment-secret",
    )
    response = client.post(
        "/v1/devices/register",
        json={
            "device_id": "api-key-only-device",
            "fcm_token": "test-token",
            "label": "test",
        },
        headers={"X-API-Key": "dev-local-key"},
    )
    assert response.status_code == 401
    assert "totp_secret" not in response.json()


def test_sandbox_runs_accepts_valid_api_key():
    response = client.get(
        "/v1/sandbox/runs",
        headers={"X-API-Key": "dev-local-key"},
    )
    assert response.status_code == 200
    assert "runs" in response.json()