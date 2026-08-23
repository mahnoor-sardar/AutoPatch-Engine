from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_shape():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert "ok" in body
    assert "postgres" in body
    assert "redis" in body
