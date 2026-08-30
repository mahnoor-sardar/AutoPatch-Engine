from app.config import settings


class LlmNotConfigured(RuntimeError):
    pass


def _litellm_chat_model(model: str) -> str:
    name = (model or "").strip()
    if name.startswith("gemini/") or not name.startswith("gemini"):
        return name
    return f"gemini/{name}"


def _extract_unified_diff(content: str) -> str:
    text = (content or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.lstrip()
    if text.startswith("```"):
        _fence, sep, rest = text.partition("\n")
        if not sep:
            raise ValueError("model did not return a unified diff")
        text = rest
        closing = text.rfind("\n```")
        if closing != -1:
            text = text[:closing]
        elif text.endswith("```"):
            text = text[:-3]
    if "diff --git" not in text and not text.lstrip().startswith("---"):
        raise ValueError("model did not return a unified diff")
    return text.strip("\n") + "\n"


def generate_patch(
    *,
    path: str,
    source: str,
    test_source: str,
    stderr: str,
    exception_type: str | None,
    previous_error: str | None = None,
) -> str:
    if not settings.llm_api_key:
        raise LlmNotConfigured("LLM_API_KEY is not set")

    from litellm import completion

    prompt = (
        "You are AutoPatch Engine. Return ONLY a unified git diff that "
        "fixes the bug. Do not wrap in markdown.\n\n"
        f"File: {path}\n"
        f"Exception: {exception_type}\n"
        f"Test:\n{test_source}\n\n"
        f"Stderr:\n{stderr}\n\n"
        f"Previous error:\n{previous_error or ''}\n\n"
        f"Current source:\n{source}\n"
    )

    model = _litellm_chat_model(settings.llm_model)
    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "api_key": settings.llm_api_key,
    }
    if settings.llm_api_base and not model.startswith("gemini/"):
        kwargs["api_base"] = settings.llm_api_base

    response = completion(**kwargs)
    return _extract_unified_diff(response.choices[0].message.content or "")
