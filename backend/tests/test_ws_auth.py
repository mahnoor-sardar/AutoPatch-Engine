import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.auth import (
    WS_TICKET_TTL_SECONDS,
    issue_ws_ticket,
    secrets_match,
    ticket_from_ws_protocols,
    verify_ws_ticket,
    ws_api_key_header_allowed,
    ws_subprotocol_for_ticket,
)
from app.config import settings
from app.main import app


client = TestClient(app)
HEADERS = {"X-API-Key": "dev-local-key"}


def test_ws_api_key_header_allowed_only_in_dev_envs(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "test")
    assert ws_api_key_header_allowed() is True
    monkeypatch.setattr(settings, "app_env", "production")
    assert ws_api_key_header_allowed() is False


def test_secrets_match_uses_compare_digest_and_rejects_odd_values():
    assert secrets_match("dev-local-key", "dev-local-key") is True
    assert secrets_match("wrong", "dev-local-key") is False
    assert secrets_match(None, "dev-local-key") is False
    assert secrets_match("ab", "abcd") is False
    assert secrets_match("odd-length-x", "evenlen") is False


def test_ticket_endpoint_requires_api_key():
    response = client.get("/v1/ws/ticket")
    assert response.status_code == 401


def test_ticket_endpoint_returns_ticket_with_valid_key():
    response = client.get("/v1/ws/ticket", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["expires_in"] == WS_TICKET_TTL_SECONDS
    ticket = body["ticket"]
    assert verify_ws_ticket(ticket) is True


def test_ticket_expires_after_ttl():
    issued_at = 1_000_000
    ticket, ttl = issue_ws_ticket(now=issued_at)
    assert ttl == WS_TICKET_TTL_SECONDS
    assert verify_ws_ticket(ticket, now=issued_at) is True
    # Current production rule is `moment - issued_at > TTL`, so exact TTL is valid.
    assert verify_ws_ticket(ticket, now=issued_at + WS_TICKET_TTL_SECONDS) is True
    assert verify_ws_ticket(ticket, now=issued_at + WS_TICKET_TTL_SECONDS + 1) is False


def test_malformed_and_tampered_tickets_are_rejected():
    ticket, _ttl = issue_ws_ticket()
    ts, signature = ticket.split(".", 1)
    assert verify_ws_ticket("") is False
    assert verify_ws_ticket("noticket") is False
    assert verify_ws_ticket("nope.zz") is False
    assert verify_ws_ticket(f"{ts}.{signature[:-1]}0") is False
    assert verify_ws_ticket("abc.not-hex") is False


def test_websocket_rejects_missing_authentication():
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/v1/ws/runs"):
            raise AssertionError("unauthenticated websocket must not stay open")
    assert exc_info.value.code == 1008


def test_websocket_rejects_wrong_api_key_header():
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/v1/ws/runs",
            headers={"X-API-Key": "wrong"},
        ):
            raise AssertionError("wrong api key must not stay open")
    assert exc_info.value.code == 1008


def test_websocket_query_api_key_no_longer_authenticates():
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/v1/ws/runs?api_key=dev-local-key"):
            raise AssertionError("query api_key must not authenticate")
    assert exc_info.value.code == 1008


def test_websocket_accepts_valid_header_key(monkeypatch):
    _stub_empty_runs(monkeypatch)

    async def fake_subscribe():
        raise WebSocketDisconnect()
        yield  # pragma: no cover

    monkeypatch.setattr(
        "app.services.events.subscribe_run_updates",
        fake_subscribe,
    )
    monkeypatch.setattr(settings, "app_env", "test")
    with client.websocket_connect(
        "/v1/ws/runs",
        headers={"X-API-Key": "dev-local-key"},
    ) as ws:
        first = ws.receive_json()
        assert "runs" in first


def test_websocket_rejects_api_key_header_outside_dev_envs(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/v1/ws/runs",
            headers={"X-API-Key": "dev-local-key"},
        ):
            raise AssertionError("production must not accept WS API-key headers")
    assert exc_info.value.code == 1008


def test_websocket_accepts_ticket_in_production(monkeypatch):
    _stub_empty_runs(monkeypatch)

    async def fake_subscribe():
        raise WebSocketDisconnect()
        yield  # pragma: no cover

    monkeypatch.setattr(
        "app.services.events.subscribe_run_updates",
        fake_subscribe,
    )
    monkeypatch.setattr(settings, "app_env", "production")
    ticket = client.get("/v1/ws/ticket", headers=HEADERS).json()["ticket"]
    protocol = ws_subprotocol_for_ticket(ticket)
    with client.websocket_connect(
        "/v1/ws/runs",
        subprotocols=[protocol],
    ) as ws:
        first = ws.receive_json()
        assert "runs" in first


def test_websocket_accepts_valid_ticket_subprotocol(monkeypatch):
    _stub_empty_runs(monkeypatch)

    async def fake_subscribe():
        raise WebSocketDisconnect()
        yield  # pragma: no cover

    monkeypatch.setattr(
        "app.services.events.subscribe_run_updates",
        fake_subscribe,
    )
    ticket = client.get("/v1/ws/ticket", headers=HEADERS).json()["ticket"]
    protocol = ws_subprotocol_for_ticket(ticket)
    with client.websocket_connect(
        "/v1/ws/runs",
        subprotocols=[protocol],
    ) as ws:
        first = ws.receive_json()
        assert "runs" in first


def test_websocket_rejects_expired_ticket_subprotocol():
    ticket, _ttl = issue_ws_ticket(now=1_000_000)
    protocol = ws_subprotocol_for_ticket(ticket)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/v1/ws/runs",
            subprotocols=[protocol],
        ):
            raise AssertionError("expired ticket must not authenticate")
    assert exc_info.value.code == 1008


def test_ticket_from_ws_protocols_parses_prefix():
    assert ticket_from_ws_protocols(None) is None
    assert ticket_from_ws_protocols("autopatch.1.abc") == "1.abc"
    assert ticket_from_ws_protocols("other, autopatch.2.def") == "2.def"


def _stub_empty_runs(monkeypatch):
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
