import time

from fastapi.testclient import TestClient
from redis import Redis

from app.config import settings
from app.db import get_db
from app.main import app
from app.models import Device, Repository
from app.workers.celery_app import celery_app
from app.workers.tasks import clone_and_index

client = TestClient(app)


def _broker_bodies(redis_client: Redis) -> list[str]:
    bodies: list[str] = []
    queue = celery_app.conf.task_default_queue
    for item in redis_client.lrange(queue, 0, -1):
        bodies.append(item.decode() if isinstance(item, bytes) else item)
    unacked = redis_client.hgetall("unacked")
    for value in unacked.values():
        text = value.decode() if isinstance(value, bytes) else value
        bodies.append(text)
    return bodies


def _worker_stored_result(redis_client: Redis, task_id: str) -> bool:
    meta_key = f"celery-task-meta-{task_id}"
    deadline = time.time() + 5
    while time.time() < deadline:
        if redis_client.exists(meta_key):
            return True
        time.sleep(0.1)
    return False


def test_fastapi_and_celery_share_redis_broker():
    assert settings.redis_url == celery_app.conf.broker_url
    assert celery_app.conf.task_default_queue == "celery"
    redis_client = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
    try:
        assert redis_client.ping() is True
    finally:
        redis_client.close()


def test_clone_and_index_is_published_to_worker_queue():
    assert settings.redis_url == celery_app.conf.broker_url
    queue = celery_app.conf.task_default_queue
    redis_client = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
    try:
        assert redis_client.ping() is True
        result = clone_and_index.apply_async(args=[0], queue=queue)
        assert result.id
        queued = any(
            "clone_and_index" in body and result.id in body
            for body in _broker_bodies(redis_client)
        )
        consumed = _worker_stored_result(redis_client, result.id)
        assert queued or consumed, (
            "clone_and_index was neither sitting on Redis queue "
            f"{queue!r} nor consumed into celery-task-meta-{result.id}"
        )
    finally:
        redis_client.close()


def test_post_sandbox_run_creates_gate_and_publishes_clone_and_index(monkeypatch):
    published = []
    real_delay = clone_and_index.delay

    def capturing_delay(run_id):
        result = real_delay(run_id)
        published.append((run_id, result.id))
        return result

    class FakeQuery:
        def __init__(self, result):
            self._result = result

        def filter(self, *args, **kwargs):
            return self

        def one_or_none(self):
            return self._result

        def all(self):
            return []

    class FakeDB:
        def query(self, model):
            if model is Device:
                return FakeQuery(
                    Device(
                        device_id="dev-1",
                        fcm_token="test-fcm",
                        totp_secret="JBSWY3DPEHPK3PXP",
                        label="test-approval",
                        revoked_at=None,
                    )
                )
            return FakeQuery(
                Repository(
                    full_name="mahnoor-sardar/AutoPatch-Engine",
                    installation_id=1,
                    default_branch="main",
                )
            )

        def add(self, obj):
            if getattr(obj, "id", None) is None:
                obj.id = 362

        def commit(self):
            pass

        def refresh(self, obj):
            if getattr(obj, "id", None) is None:
                obj.id = 362

    monkeypatch.setattr("app.services.fcm.send_push", lambda *a, **k: "ok")
    monkeypatch.setattr(
        "app.routers.sandbox.clone_and_index.delay",
        capturing_delay,
    )
    app.dependency_overrides[get_db] = lambda: FakeDB()
    redis_client = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
    try:
        assert redis_client.ping() is True
        assert settings.redis_url == celery_app.conf.broker_url
        response = client.post(
            "/v1/sandbox/runs",
            headers={"X-API-Key": "dev-local-key"},
            json={
                "repo": "mahnoor-sardar/AutoPatch-Engine",
                "ref": "main",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == 362
        assert body["status"] == "queued"
        assert body["approval_gate"] == "sandbox_provision"
        assert body["approval_status"] == "pending"
        assert len(published) == 1
        assert published[0][0] == 362
        task_id = published[0][1]
        queued = any(
            "clone_and_index" in item and ("362" in item or task_id in item)
            for item in _broker_bodies(redis_client)
        )
        consumed = _worker_stored_result(redis_client, task_id)
        assert queued or consumed, (
            "POST /v1/sandbox/runs published clone_and_index but Redis queue "
            f"{celery_app.conf.task_default_queue} did not retain it and the "
            f"worker did not write celery-task-meta-{task_id}"
        )
    finally:
        app.dependency_overrides.clear()
        redis_client.close()
