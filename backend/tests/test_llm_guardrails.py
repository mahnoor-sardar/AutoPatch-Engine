from types import SimpleNamespace

from app.services.patcher import (
    LlmRequestTimeout,
    LlmTokenBudgetExceeded,
    diffs_are_identical,
    generate_patch,
    normalize_unified_diff,
    usage_tokens_from_response,
)


VALID_DIFF = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"


def _enable_llm(monkeypatch, **overrides):
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    for name, value in overrides.items():
        monkeypatch.setattr(settings, name, value)


def _completion(content=VALID_DIFF, usage=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=usage,
    )


def test_normalize_diff_ignores_index_and_timestamps():
    left = (
        "diff --git a/x.py b/x.py\n"
        "index abc123..def456 100644\n"
        "--- a/x.py\t2024-01-01\n"
        "+++ b/x.py\t2024-01-02\n"
        "+fixed  \r\n"
    )
    right = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "+fixed\n"
    )
    assert diffs_are_identical(left, right)
    assert normalize_unified_diff("") == ""
    assert normalize_unified_diff("\n\n") == ""


def test_usage_tokens_missing_is_none():
    assert usage_tokens_from_response(SimpleNamespace()) is None
    assert usage_tokens_from_response(SimpleNamespace(usage=None)) is None
    assert (
        usage_tokens_from_response(SimpleNamespace(usage=SimpleNamespace())) is None
    )


def test_usage_tokens_from_total_and_parts():
    assert (
        usage_tokens_from_response(
            SimpleNamespace(usage=SimpleNamespace(total_tokens=9))
        )
        == 9
    )
    assert (
        usage_tokens_from_response(
            SimpleNamespace(
                usage={"prompt_tokens": 3, "completion_tokens": 4}
            )
        )
        == 7
    )


def test_generate_patch_persists_reported_usage_only(monkeypatch):
    _enable_llm(monkeypatch)
    seen = []

    def fake_completion(**kwargs):
        seen.append(kwargs)
        return _completion(usage=SimpleNamespace(total_tokens=12))

    monkeypatch.setattr("litellm.completion", fake_completion)
    result = generate_patch(
        path="a.py",
        source="x=1",
        test_source="def test(): pass",
        stderr="boom",
        exception_type="ValueError",
    )
    assert result.diff.startswith("diff --git")
    assert result.tokens_used == 12
    assert seen[0]["timeout"] == 60.0


def test_generate_patch_does_not_invent_usage(monkeypatch):
    _enable_llm(monkeypatch)
    monkeypatch.setattr(
        "litellm.completion",
        lambda **kwargs: _completion(),
    )
    result = generate_patch(
        path="a.py",
        source="x=1",
        test_source="def test(): pass",
        stderr="boom",
        exception_type="ValueError",
    )
    assert result.tokens_used is None


def test_generate_patch_enforces_token_budget_before_request(monkeypatch):
    _enable_llm(monkeypatch, llm_token_budget=10)
    called = []

    def fake_completion(**kwargs):
        called.append(kwargs)
        return _completion()

    monkeypatch.setattr("litellm.completion", fake_completion)
    try:
        generate_patch(
            path="a.py",
            source="x=1",
            test_source="def test(): pass",
            stderr="boom",
            exception_type="ValueError",
            tokens_used=10,
        )
    except LlmTokenBudgetExceeded:
        assert called == []
        return
    raise AssertionError("expected LlmTokenBudgetExceeded")


def test_generate_patch_times_out_safely(monkeypatch):
    _enable_llm(monkeypatch, llm_timeout_seconds=1.5)

    def fake_completion(**kwargs):
        assert kwargs["timeout"] == 1.5
        raise TimeoutError("deadline")

    monkeypatch.setattr("litellm.completion", fake_completion)
    try:
        generate_patch(
            path="a.py",
            source="x=1",
            test_source="def test(): pass",
            stderr="boom",
            exception_type="ValueError",
        )
    except LlmRequestTimeout as exc:
        assert "timed out" in str(exc)
        return
    raise AssertionError("expected LlmRequestTimeout")
