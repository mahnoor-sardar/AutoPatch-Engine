import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.db import SessionLocal
from app.main import app
from app.models import PatchAttempt, ReproductionAttempt, SandboxRun
from app.services.e2b_runner import (
    agent_log_scope,
    run_sandbox_command,
    sanitize_log_text,
)
from app.services.events import RUN_CHANNEL, publish_agent_log
from app.services.harness import _run_command


client = TestClient(app)


def test_sanitize_log_redacts_github_token_and_clone_url():
    token = "ghs_secretvalue1234567890abcd"
    raw = (
        f"fatal: {token} "
        "https://x-access-token:ghs_other@github.com/a/b.git "
        "API_KEY=supersecret "
        "ghp_abcdefghij"
    )
    cleaned = sanitize_log_text(raw, token)
    assert token not in cleaned
    assert "ghs_" not in cleaned
    assert "ghp_" not in cleaned
    assert "x-access-token:" not in cleaned
    assert "[REDACTED]" in cleaned
    assert "https://github.com/" in cleaned


def test_publish_agent_log_does_not_call_fcm(monkeypatch):
    seen = []

    class FakeRedis:
        def publish(self, channel, body):
            seen.append((channel, json.loads(body)))

        def close(self):
            return None

    class FakeFactory:
        @staticmethod
        def from_url(url, **kwargs):
            return FakeRedis()

    def boom(*args, **kwargs):
        raise AssertionError("FCM must not run for agent logs")

    monkeypatch.setattr("app.services.events.Redis", FakeFactory)
    monkeypatch.setattr("app.services.events.fcm.send_push_with_timeout", boom)
    publish_agent_log(12, "stdout", "pytest output\n", token="")
    assert seen
    assert seen[0][0] == RUN_CHANNEL
    payload = seen[0][1]
    assert payload["type"] == "agent_log"
    assert payload["run_id"] == 12
    assert payload["stream"] == "stdout"
    assert payload["chunk"] == "pytest output\n"


def test_publish_agent_log_redacts_token(monkeypatch):
    seen = []

    class FakeRedis:
        def publish(self, channel, body):
            seen.append(json.loads(body))

        def close(self):
            return None

    class FakeFactory:
        @staticmethod
        def from_url(url, **kwargs):
            return FakeRedis()

    monkeypatch.setattr("app.services.events.Redis", FakeFactory)
    publish_agent_log(1, "stderr", "using ghs_abcdefghijklmnopqrstuv", token="")
    assert "[REDACTED_GITHUB_TOKEN]" in seen[0]["chunk"]
    assert "ghs_" not in seen[0]["chunk"]


def test_run_sandbox_command_streams_stdout_and_stderr(monkeypatch):
    published = []

    def capture(run_id, stream, chunk, token=""):
        published.append((run_id, stream, chunk, token))

    monkeypatch.setattr("app.services.events.publish_agent_log", capture)

    class Commands:
        def run(self, command, timeout, on_stdout=None, on_stderr=None):
            assert command == "echo hi"
            if on_stdout:
                on_stdout("out-line\n")
            if on_stderr:
                on_stderr("err-line\n")
            return SimpleNamespace(stdout="out-line\n", stderr="err-line\n", exit_code=0)

    sandbox = SimpleNamespace(commands=Commands())
    with agent_log_scope(99, token="tok"):
        result = run_sandbox_command(sandbox, "echo hi", 10)
    assert result.exit_code == 0
    streams = {(item[1], item[2]) for item in published}
    assert ("stdout", "out-line\n") in streams
    assert ("stderr", "err-line\n") in streams
    assert all(item[0] == 99 for item in published)
    assert all(item[3] == "tok" for item in published)


def test_run_sandbox_command_fallback_without_callbacks(monkeypatch):
    published = []
    monkeypatch.setattr(
        "app.services.events.publish_agent_log",
        lambda run_id, stream, chunk, token="": published.append((stream, chunk)),
    )

    class Commands:
        def run(self, command, timeout):
            return SimpleNamespace(stdout="full-out", stderr="full-err", exit_code=0)

    sandbox = SimpleNamespace(commands=Commands())
    with agent_log_scope(7):
        run_sandbox_command(sandbox, "ls", 5)
    assert ("stdout", "full-out") in published
    assert ("stderr", "full-err") in published


def test_harness_run_command_uses_e2b_runner(monkeypatch):
    seen = []

    def fake_run(sandbox, command, timeout, on_stdout=None, on_stderr=None):
        seen.append(command)
        return SimpleNamespace(stdout="ok", stderr="", exit_code=0)

    monkeypatch.setattr("app.services.harness.run_sandbox_command", fake_run)
    result = _run_command(object(), "pytest -q", 30)
    assert result.stdout == "ok"
    assert seen == ["pytest -q"]


def test_historical_logs_endpoint_returns_stored_output():
    db = SessionLocal()
    try:
        run = SandboxRun(status="completed", repo="a/b", ref="main")
        db.add(run)
        db.commit()
        db.refresh(run)
        db.add(
            ReproductionAttempt(
                run_id=run.id,
                stack_trace="ZeroDivisionError",
                stdout="1 failed",
                stderr="ZeroDivisionError: boom",
                reproduced=True,
            )
        )
        db.add(
            PatchAttempt(
                run_id=run.id,
                attempt_number=1,
                diff="diff --git a/x b/x\n",
                status="applied",
                stdout="1 passed",
                stderr="",
            )
        )
        db.commit()
        response = client.get(
            f"/v1/sandbox/runs/{run.id}/logs",
            headers={"X-API-Key": "dev-local-key"},
        )
        assert response.status_code == 200
        body = response.json()
        chunks = body["chunks"]
        texts = [item["chunk"] for item in chunks]
        assert "1 failed" in texts
        assert "ZeroDivisionError: boom" in texts
        assert "1 passed" in texts
        assert {item["stream"] for item in chunks} <= {"stdout", "stderr"}
    finally:
        db.close()


def test_websocket_delivers_agent_log_without_requiring_runs(monkeypatch):
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
            "data": json.dumps(
                {
                    "type": "agent_log",
                    "run_id": 5,
                    "stream": "stderr",
                    "chunk": "boom\n",
                }
            ),
        }
        raise WebSocketDisconnect()

    monkeypatch.setattr(
        "app.services.events.subscribe_run_updates",
        fake_subscribe,
    )
    with client.websocket_connect(
        "/v1/ws/runs",
        headers={"X-API-Key": "dev-local-key"},
    ) as ws:
        first = ws.receive_json()
        assert "runs" in first
        second = ws.receive_json()
        assert second["event"]["type"] == "agent_log"
        assert second["event"]["chunk"] == "boom\n"
        assert second["event"]["stream"] == "stderr"
        assert "runs" not in second
