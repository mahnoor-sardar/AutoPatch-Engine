from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_sandbox_runs_requires_api_key():
    response = client.get("/v1/sandbox/runs")

    assert response.status_code == 401