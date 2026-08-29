from app.config import settings


class LlmNotConfigured(RuntimeError):
    pass


def _litellm_chat_model(model: str) -> str:
    name = (model or "").strip()
    if name.startswith("gemini/") or not name.startswith("gemini"):
        return name
    return f"gemini/{name}"


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

    kwargs: dict = {
        "model": _litellm_chat_model(settings.llm_model),
        "messages": [{"role": "user", "content": prompt}],
        "api_key": settings.llm_api_key,
    }
    if settings.llm_api_base:
        kwargs["api_base"] = settings.llm_api_base

    response = completion(**kwargs)
    content = response.choices[0].message.content or ""
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("diff"):
            pass
        else:
            content = content.split("\n", 1)[-1]
    if "diff --git" not in content and not content.startswith("---"):
        raise ValueError("model did not return a unified diff")
    return content
