from types import SimpleNamespace

from app.config import settings
from app.services.gemini import (
    GeminiNotConfigured,
    diagnose_reproduction,
    generate_text,
)


def test_generate_text_requires_api_key(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    try:
        generate_text("hello")
    except GeminiNotConfigured:
        return
    raise AssertionError("expected GeminiNotConfigured")


def test_generate_text_returns_model_text(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "generated reply"}],
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, timeout=30):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(settings, "gemini_model", "gemini-2.0-flash")
    monkeypatch.setattr("app.services.gemini.httpx.Client", FakeClient)

    result = generate_text("summarize this")

    assert result == "generated reply"
    assert captured["url"].endswith("/models/gemini-2.0-flash:generateContent")
    assert "generativelanguage.googleapis.com" in captured["url"]
    assert captured["headers"]["x-goog-api-key"] == "test-key"
    assert captured["json"]["contents"][0]["parts"][0]["text"] == "summarize this"
    assert "test-key" not in captured["url"]


def test_generate_text_rejects_empty_candidates(monkeypatch):
    class FakeClient:
        def __init__(self, timeout=30):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"candidates": []},
            )

    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr("app.services.gemini.httpx.Client", FakeClient)

    try:
        generate_text("hello")
    except ValueError as exc:
        assert "no candidates" in str(exc)
        return
    raise AssertionError("expected ValueError")


def test_diagnose_reproduction_asks_for_diagnosis_not_a_patch(monkeypatch):
    seen = {}

    def fake_generate_text(prompt: str) -> str:
        seen["prompt"] = prompt
        return "calculate divides by zero at line 2."

    monkeypatch.setattr("app.services.gemini.generate_text", fake_generate_text)
    result = diagnose_reproduction(
        path="backend/app/services/math.py",
        name="calculate",
        line=2,
        exception_type="ZeroDivisionError",
        source="def calculate():\n    return 10 / 0\n",
        test_source="def test_reproduces_calculate_failure(): pass",
        stderr="ZeroDivisionError: division by zero",
        stack_trace="ZeroDivisionError: division by zero",
    )
    assert result == "calculate divides by zero at line 2."
    prompt = seen["prompt"]
    assert "backend/app/services/math.py" in prompt
    assert "calculate" in prompt
    assert "ZeroDivisionError" in prompt
    assert "Do not output a git diff" in prompt
    assert "GEMINI_API_KEY" not in prompt
    assert "test-key" not in prompt


def test_diagnose_reproduction_clips_long_source(monkeypatch):
    seen = {}

    def fake_generate_text(prompt: str) -> str:
        seen["prompt"] = prompt
        return "ok"

    monkeypatch.setattr("app.services.gemini.generate_text", fake_generate_text)
    diagnose_reproduction(
        path="a.py",
        name="fn",
        line=1,
        exception_type="Error",
        source="x" * 8000,
        test_source="t",
        stderr="e",
        stack_trace="s",
    )
    assert "[truncated]" in seen["prompt"]
    assert len(seen["prompt"]) < 9000
