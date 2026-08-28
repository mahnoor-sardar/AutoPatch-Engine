import httpx

from app.config import settings

GEMINI_API_ROOT = "https://generativelanguage.googleapis.com/v1beta"


class GeminiNotConfigured(RuntimeError):
    pass


def generate_text(prompt: str) -> str:
    if not settings.gemini_api_key:
        raise GeminiNotConfigured("GEMINI_API_KEY is not set")

    url = f"{GEMINI_API_ROOT}/models/{settings.gemini_model}:generateContent"
    with httpx.Client(timeout=30) as client:
        response = client.post(
            url,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": settings.gemini_api_key,
            },
            json={
                "contents": [
                    {"parts": [{"text": prompt}]},
                ]
            },
        )
    response.raise_for_status()
    payload = response.json()
    candidates = payload.get("candidates") or []
    if not candidates:
        raise ValueError("Gemini returned no candidates")
    parts = (
        (candidates[0].get("content") or {}).get("parts") or []
    )
    text = "".join(part.get("text") or "" for part in parts).strip()
    if not text:
        raise ValueError("Gemini returned an empty response")
    return text


_MAX_CONTEXT_CHARS = 4000


def _clip(text: str | None) -> str:
    value = text or ""
    if len(value) <= _MAX_CONTEXT_CHARS:
        return value
    return value[:_MAX_CONTEXT_CHARS] + "\n...[truncated]"


def diagnose_reproduction(
    *,
    path: str,
    name: str | None,
    line: int | None,
    exception_type: str | None,
    source: str,
    test_source: str,
    stderr: str,
    stack_trace: str,
) -> str:
    prompt = (
        "You are AutoPatch Engine. A reproduction test confirmed this bug. "
        "Write a concise diagnosis: the likely root cause and where it lives. "
        "Do not output a git diff, patch, or code fix.\n\n"
        f"File: {path}\n"
        f"Symbol: {name or ''}\n"
        f"Line: {line or ''}\n"
        f"Exception: {exception_type or ''}\n\n"
        f"Stack trace:\n{_clip(stack_trace)}\n\n"
        f"Reproduction test:\n{_clip(test_source)}\n\n"
        f"Stderr:\n{_clip(stderr)}\n\n"
        f"Source:\n{_clip(source)}\n"
    )
    return generate_text(prompt)
