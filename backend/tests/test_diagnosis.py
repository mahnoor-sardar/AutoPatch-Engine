from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import SandboxRun
from app.services.audit import log_audit


client = TestClient(app)
HEADERS = {"X-API-Key": "dev-local-key"}


def test_diagnosis_requires_api_key():
    response = client.get("/v1/sandbox/runs/1/diagnosis")
    assert response.status_code == 401


def test_diagnosis_unknown_run_is_not_found():
    response = client.get(
        "/v1/sandbox/runs/999999999/diagnosis",
        headers=HEADERS,
    )
    assert response.status_code == 404


def test_diagnosis_empty_when_missing():
    db = SessionLocal()
    try:
        run = SandboxRun(status="completed", repo="a/b", ref="main")
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()

    response = client.get(
        f"/v1/sandbox/runs/{run_id}/diagnosis",
        headers=HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["diagnosis"] is None
    assert body["created_at"] is None
    assert set(body.keys()) == {"run_id", "diagnosis", "created_at"}


def test_diagnosis_returns_latest_text_only():
    db = SessionLocal()
    try:
        run = SandboxRun(status="completed", repo="a/b", ref="main")
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
        log_audit(db, "diagnosis", run_id, None, "older diagnosis")
        log_audit(db, "approve", run_id, "test-device", "patch_review")
        log_audit(db, "diagnosis", run_id, None, "calculate divides by zero")
        db.commit()
    finally:
        db.close()

    response = client.get(
        f"/v1/sandbox/runs/{run_id}/diagnosis",
        headers=HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["diagnosis"] == "calculate divides by zero"
    assert body["created_at"]
    assert "api_key" not in body
    assert "gemini_api_key" not in body
    assert "device_id" not in body
