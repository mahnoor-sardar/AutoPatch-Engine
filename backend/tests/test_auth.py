from fastapi.testclient import TestClient

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