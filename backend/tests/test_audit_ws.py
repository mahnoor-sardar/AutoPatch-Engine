import json

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.db import SessionLocal
from app.main import app
from app.models import AuditEvent, SandboxRun
from app.routers.sandbox import serialize_runs
from app.services.audit import log_audit
from app.services.events import RUN_CHANNEL, publish_run_update


client = TestClient(app)


def test_serialize_runs_includes_status_and_diff():
    run = SandboxRun(
        id=3,
        status="awaiting_patch_review",
        repo="a/b",
        ref="main",
        current_diff="diff --git a/x b/x\n",
        pr_url=None,
        control_state="active",
    )
    payload = serialize_runs([run])
    assert payload["runs"][0]["id"] == 3
    assert payload["runs"][0]["current_diff"].startswith("diff --git")
    assert "pipeline_stage" in payload["runs"][0]
    assert "error" in payload["runs"][0]
    assert "ref" in payload["runs"][0]


def test_websocket_rejects_bad_key():
    try:
        with client.websocket_connect("/v1/ws/runs?api_key=wrong"):
            raise AssertionError("should have closed")
    except Exception:
        return


def test_websocket_pushes_on_redis_message(monkeypatch):
    class Query:
        def order_by(self, *args, **kwargs):
            return self

        def limit(self, n):
            return self

        def all(self):
            return []

    class DB:
        def query(self, model):
            return Query()

        def close(self):
            return None

    monkeypatch.setattr("app.db.SessionLocal", lambda: DB())

    async def fake_subscribe():
        yield {
            "type": "message",
            "data": json.dumps({"title": "Sandbox running", "body": "clone started"}),
        }
        raise WebSocketDisconnect()

    monkeypatch.setattr(
        "app.services.events.subscribe_run_updates",
        fake_subscribe,
    )
    with client.websocket_connect("/v1/ws/runs?api_key=dev-local-key") as ws:
        first = ws.receive_json()
        assert "runs" in first
        second = ws.receive_json()
        assert "runs" in second
        assert second["event"]["title"] == "Sandbox running"


def test_publish_run_update_uses_redis_pubsub(monkeypatch):
    seen = []

    class FakeRedis:
        def publish(self, channel, body):
            seen.append((channel, body))

        def close(self):
            return None

    class FakeFactory:
        @staticmethod
        def from_url(url, **kwargs):
            return FakeRedis()

    monkeypatch.setattr("app.services.events.Redis", FakeFactory)
    publish_run_update({"title": "Patch ready for review"})
    assert seen
    assert seen[0][0] == RUN_CHANNEL
    assert "Patch ready for review" in seen[0][1]


def test_log_audit_persists_expire_and_pr():
    db = SessionLocal()
    try:
        repo_run = db.query(SandboxRun).order_by(SandboxRun.id.desc()).first()
        run_id = repo_run.id if repo_run is not None else None
        log_audit(db, "expire", run_id, None, "sandbox_provision")
        log_audit(db, "pr_opened", run_id, None, "https://example/pr")
        db.commit()
        events = (
            db.query(AuditEvent)
            .filter(AuditEvent.action.in_(["expire", "pr_opened"]))
            .all()
        )
        actions = {event.action for event in events}
        assert "expire" in actions
        assert "pr_opened" in actions
    finally:
        db.close()


def test_recent_audit_returns_events_envelope():
    response = client.get(
        "/v1/sandbox/audit?limit=5",
        headers={"X-API-Key": "dev-local-key"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "events" in body
    assert isinstance(body["events"], list)
    if body["events"]:
        assert "action" in body["events"][0]
        assert "run_id" in body["events"][0]


def test_connected_repositories_returns_list():
    response = client.get(
        "/v1/github/connected",
        headers={"X-API-Key": "dev-local-key"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "repositories" in body
    assert isinstance(body["repositories"], list)
