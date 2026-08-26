from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models import Repository

client = TestClient(app)


def test_sandbox_runs_requires_api_key():
    response = client.get("/v1/sandbox/runs")

    assert response.status_code == 401


def test_sandbox_run_accepts_stack_trace():
    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def one_or_none(self):
            return Repository(
                full_name="mahnoor-sardar/AutoPatch-Engine",
                installation_id=1,
                default_branch="main",
            )

    class FakeDB:
        def query(self, model):
            return FakeQuery()

        def add(self, obj):
            if hasattr(obj, "id") and obj.id is None:
                obj.id = 999

        def commit(self):
            pass

        def refresh(self, obj):
            obj.id = 999

    app.dependency_overrides[get_db] = lambda: FakeDB()

    try:
        response = client.post(
            "/v1/sandbox/runs",
            headers={"X-API-Key": "dev-local-key"},
            json={
                "repo": "mahnoor-sardar/AutoPatch-Engine",
                "ref": "main",
                "stack_trace": (
                    "Traceback (most recent call last):\n"
                    '  File "backend/broken.py", line 2, in broken\n'
                    "    return 1 / 0\n"
                    "ZeroDivisionError: division by zero\n"
                ),
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "queued"

    finally:
        app.dependency_overrides.clear()