from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import AuditEvent, SandboxRun
from app.services.audit import (
    ACTOR_ANDROID,
    ACTOR_SYSTEM,
    ACTOR_WORKER,
    RESULT_EXPIRED,
    RESULT_REJECTED,
    RESULT_SUCCESS,
    log_audit,
)


client = TestClient(app)
HEADERS = {"X-API-Key": "dev-local-key"}


def _create_run(db, repo="a/b"):
    run = SandboxRun(status="queued", repo=repo, ref="main")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def test_audit_requires_api_key():
    response = client.get("/v1/sandbox/runs/1/audit")
    assert response.status_code == 401


def test_audit_unknown_run_is_not_found():
    response = client.get(
        "/v1/sandbox/runs/999999999/audit",
        headers=HEADERS,
    )
    assert response.status_code == 404


def test_audit_empty_when_missing():
    db = SessionLocal()
    try:
        run_id = _create_run(db).id
    finally:
        db.close()

    response = client.get(
        f"/v1/sandbox/runs/{run_id}/audit",
        headers=HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["events"] == []


def test_audit_returns_events_newest_first_with_structured_fields():
    db = SessionLocal()
    try:
        run_id = _create_run(db).id
        log_audit(
            db,
            "approve",
            run_id,
            "device-a",
            "sandbox_provision",
            actor=ACTOR_ANDROID,
            result=RESULT_SUCCESS,
            event_metadata={"gate": "sandbox_provision"},
        )
        log_audit(
            db,
            "diagnosis",
            run_id,
            None,
            "root cause text",
            actor=ACTOR_WORKER,
            result=RESULT_SUCCESS,
        )
        log_audit(
            db,
            "pr_opened",
            run_id,
            None,
            "https://example/pr/1",
            actor=ACTOR_WORKER,
            result=RESULT_SUCCESS,
            event_metadata={"pr_url": "https://example/pr/1"},
        )
        db.commit()
    finally:
        db.close()

    response = client.get(
        f"/v1/sandbox/runs/{run_id}/audit",
        headers=HEADERS,
    )
    assert response.status_code == 200
    events = response.json()["events"]
    assert [event["action"] for event in events] == [
        "pr_opened",
        "diagnosis",
        "approve",
    ]
    assert events[0]["detail"] == "https://example/pr/1"
    assert events[0]["actor"] == ACTOR_WORKER
    assert events[0]["result"] == RESULT_SUCCESS
    assert events[0]["metadata"] == {"pr_url": "https://example/pr/1"}
    assert events[2]["device_id"] == "device-a"
    assert events[2]["created_at"]
    assert "otp_code" not in str(events)
    assert "totp_secret" not in str(events)
    assert "approval_token" not in str(events)
    assert "api_key" not in str(events)


def test_audit_existing_event_types():
    db = SessionLocal()
    try:
        run_id = _create_run(db).id
        log_audit(
            db,
            "approve",
            run_id,
            "dev-1",
            "patch_review",
            actor=ACTOR_ANDROID,
            result=RESULT_SUCCESS,
            event_metadata={"gate": "patch_review"},
        )
        log_audit(
            db,
            "reject",
            run_id,
            "dev-1",
            "merge",
            actor=ACTOR_ANDROID,
            result=RESULT_REJECTED,
            event_metadata={"gate": "merge"},
        )
        log_audit(
            db,
            "expire",
            run_id,
            None,
            "sandbox_provision",
            actor=ACTOR_SYSTEM,
            result=RESULT_EXPIRED,
            event_metadata={"gate": "sandbox_provision"},
        )
        log_audit(
            db,
            "diagnosis",
            run_id,
            None,
            "calculate divides by zero",
            actor=ACTOR_WORKER,
            result=RESULT_SUCCESS,
        )
        log_audit(
            db,
            "pr_opened",
            run_id,
            None,
            "https://example/pr",
            actor=ACTOR_WORKER,
            result=RESULT_SUCCESS,
        )
        db.commit()
    finally:
        db.close()

    response = client.get(
        f"/v1/sandbox/runs/{run_id}/audit",
        headers=HEADERS,
    )
    assert response.status_code == 200
    actions = {event["action"] for event in response.json()["events"]}
    assert actions == {
        "approve",
        "reject",
        "expire",
        "diagnosis",
        "pr_opened",
    }


def test_audit_isolated_to_requested_run():
    db = SessionLocal()
    try:
        run_a = _create_run(db, repo="owner/a")
        run_b = _create_run(db, repo="owner/b")
        log_audit(db, "approve", run_a.id, "dev-a", "sandbox_provision")
        log_audit(db, "reject", run_b.id, "dev-b", "sandbox_provision")
        db.commit()
        run_a_id = run_a.id
        run_b_id = run_b.id
    finally:
        db.close()

    body_a = client.get(
        f"/v1/sandbox/runs/{run_a_id}/audit",
        headers=HEADERS,
    ).json()
    body_b = client.get(
        f"/v1/sandbox/runs/{run_b_id}/audit",
        headers=HEADERS,
    ).json()
    assert [event["action"] for event in body_a["events"]] == ["approve"]
    assert [event["action"] for event in body_b["events"]] == ["reject"]
    assert all(event["device_id"] != "dev-b" for event in body_a["events"])


def test_log_audit_does_not_commit_unless_requested():
    db = SessionLocal()
    try:
        run_id = _create_run(db).id
        log_audit(db, "pause", run_id, "dev-1", "pause")
        db.rollback()
        count = (
            db.query(AuditEvent)
            .filter(AuditEvent.run_id == run_id, AuditEvent.action == "pause")
            .count()
        )
        assert count == 0

        log_audit(db, "kill", run_id, "dev-1", "kill", commit=True)
        db.expire_all()
        persisted = (
            db.query(AuditEvent)
            .filter(AuditEvent.run_id == run_id, AuditEvent.action == "kill")
            .one()
        )
        assert persisted.action == "kill"
    finally:
        db.close()


def test_log_audit_strips_sensitive_metadata():
    db = SessionLocal()
    try:
        run_id = _create_run(db).id
        event = log_audit(
            db,
            "approve",
            run_id,
            "dev-1",
            "sandbox_provision",
            event_metadata={
                "gate": "sandbox_provision",
                "otp_code": "123456",
                "totp_secret": "ABCDEF",
                "approval_token": "abc",
                "api_key": "secret-key",
            },
            commit=True,
        )
        assert event.event_metadata == {"gate": "sandbox_provision"}
    finally:
        db.close()
