import pytest

from app.config import settings
from app.workers import tasks as worker_tasks


@pytest.fixture(autouse=True)
def _default_patch_pipeline_flags(monkeypatch):
    """Keep the patch state machine on unless a test opts into the audit stop."""
    monkeypatch.setattr(settings, "autopatch_stop_after_repro", False)
    monkeypatch.setattr(
        worker_tasks,
        "diagnose_reproduction",
        lambda **kwargs: "test diagnosis",
    )
