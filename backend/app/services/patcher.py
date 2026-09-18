import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.config import settings
from app.services.e2b_runner import MAX_FILE_BYTES, MAX_FILES, sanitize_log_text
from app.services.ripgrep import SearchTimedOut, search_in_files


class LlmNotConfigured(RuntimeError):
    pass


class LlmRequestTimeout(RuntimeError):
    pass


class LlmTokenBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class PatchGenerationResult:
    diff: str
    tokens_used: int | None = None


logger = logging.getLogger(__name__)

MAX_PATCH_TOOL_ROUNDS = 8
MAX_TOOL_OUTPUT_CHARS = 8000
MAX_DIAGNOSIS_CHARS = 4000
MAX_SEARCH_HITS = 40
MAX_SEARCH_PATTERN_CHARS = 256
MAX_SEARCH_LINE_CHARS = 2048
MAX_REGEX_REPEAT = 64
SEARCH_TIMEOUT_SECONDS = 1.0

_NESTED_QUANTIFIER = re.compile(r"\([^()]*[+*][^()]*\)[+*?{]")
_QUANTIFIER_REPEAT = re.compile(r"\{(\d+)(?:,(\d*))?\}")

_PATCH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read one source file from the cloned repository snapshot. "
                "Path must be a repository-relative file already loaded."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repository-relative path",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": (
                "Search the cloned repository snapshot with a regular expression. "
                "Only already-loaded files are searched."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regular expression to search for",
                    }
                },
                "required": ["pattern"],
            },
        },
    },
]


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


def _clip_tool_output(text: str, limit: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    text = sanitize_log_text(text or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _clip_diagnosis(text: str | None) -> str:
    return _clip_tool_output(text or "", MAX_DIAGNOSIS_CHARS)


def _bounded_files(files: dict[str, str] | None) -> dict[str, str]:
    if not files:
        return {}
    bounded: dict[str, str] = {}
    for path, source in files.items():
        if len(bounded) >= MAX_FILES:
            break
        text = source if isinstance(source, str) else ""
        encoded = text.encode("utf-8")
        if len(encoded) > MAX_FILE_BYTES:
            text = encoded[:MAX_FILE_BYTES].decode("utf-8", "ignore")
        bounded[path.replace("\\", "/")] = text
    return bounded


def _normalize_relative_path(path: str) -> str:
    return (path or "").strip().replace("\\", "/")


def _is_absolute_snapshot_path(raw: str) -> bool:
    lowered = raw.lower()
    if lowered.startswith("file:"):
        return True
    if raw.startswith("//") or raw.startswith("\\\\"):
        return True
    if raw.startswith("/") or raw.startswith("~"):
        return True
    first = raw.split("/", 1)[0]
    return len(first) >= 2 and first[1] == ":"


def _has_path_traversal(raw: str) -> bool:
    return ".." in PurePosixPath(raw).parts


def _unsafe_search_pattern(pattern: str) -> str | None:
    if _NESTED_QUANTIFIER.search(pattern):
        return "nested quantifiers are not allowed"
    for match in _QUANTIFIER_REPEAT.finditer(pattern):
        low = int(match.group(1))
        high_raw = match.group(2)
        if low > MAX_REGEX_REPEAT:
            return "repetition is too large"
        if high_raw:
            if int(high_raw) > MAX_REGEX_REPEAT:
                return "repetition is too large"
        elif high_raw == "":
            return "unbounded repetition is too large"
    return None


def resolve_snapshot_path(path: str, files: dict[str, str]) -> str | None:
    """Return a map key if path is a safe relative path present in `files`."""
    raw = _normalize_relative_path(path)
    if not raw or _is_absolute_snapshot_path(raw) or _has_path_traversal(raw):
        return None
    parts: list[str] = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        parts.append(part)
    if not parts:
        return None
    normalized = "/".join(parts)
    if normalized in files:
        return normalized
    return None


def run_read_file_tool(files: dict[str, str], path: str) -> str:
    snapshot = _bounded_files(files)
    if not isinstance(path, str):
        return "error: path must be a string"
    raw = _normalize_relative_path(path)
    if _is_absolute_snapshot_path(raw):
        return "error: absolute paths are not allowed"
    if _has_path_traversal(raw):
        return "error: path traversal is not allowed"
    key = resolve_snapshot_path(path, snapshot)
    if key is None:
        return "error: file not found in repository snapshot"
    return _clip_tool_output(snapshot[key])


def run_search_code_tool(files: dict[str, str], pattern: str) -> str:
    snapshot = _bounded_files(files)
    if not isinstance(pattern, str):
        return "error: pattern must be a string"
    if not pattern:
        return "error: pattern is required"
    if len(pattern) > MAX_SEARCH_PATTERN_CHARS:
        return "error: pattern is too long"
    unsafe = _unsafe_search_pattern(pattern)
    if unsafe:
        return f"error: {unsafe}"
    try:
        re.compile(pattern)
    except re.error as exc:
        return f"error: invalid search pattern: {exc}"

    deadline = time.monotonic() + SEARCH_TIMEOUT_SECONDS
    try:
        hits = search_in_files(
            snapshot,
            pattern,
            max_hits=MAX_SEARCH_HITS,
            deadline=deadline,
            max_line_chars=MAX_SEARCH_LINE_CHARS,
        )
    except SearchTimedOut:
        return "error: search timed out"
    except re.error as exc:
        return f"error: invalid search pattern: {exc}"

    lines: list[str] = []
    for rel, line_no, line in hits[:MAX_SEARCH_HITS]:
        lines.append(f"{rel}:{line_no}:{line}")
    if len(hits) >= MAX_SEARCH_HITS:
        lines.append("...[further matches omitted]")
    if not lines:
        return "error: no matches"
    return _clip_tool_output("\n".join(lines))


def _tool_calls_from_message(message) -> list:
    raw = getattr(message, "tool_calls", None)
    if raw:
        return list(raw)
    if isinstance(message, dict) and message.get("tool_calls"):
        return list(message["tool_calls"])
    return []


def _tool_call_id(call, index: int) -> str:
    if isinstance(call, dict):
        return str(call.get("id") or f"call_{index}")
    return str(getattr(call, "id", None) or f"call_{index}")


def _tool_call_name_and_args(call) -> tuple[str, dict | None]:
    if isinstance(call, dict):
        fn = call.get("function") or {}
        name = fn.get("name") or call.get("name") or ""
        arguments = fn.get("arguments") or call.get("arguments") or "{}"
    else:
        fn = getattr(call, "function", None)
        name = (
            getattr(fn, "name", None)
            or getattr(call, "name", None)
            or ""
        )
        arguments = (
            getattr(fn, "arguments", None)
            or getattr(call, "arguments", None)
            or "{}"
        )
    if arguments is None:
        return str(name), None
    if isinstance(arguments, dict):
        return str(name), arguments
    if not isinstance(arguments, str):
        return str(name), None
    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        return str(name), None
    if not isinstance(payload, dict):
        return str(name), None
    return str(name), payload


def _assistant_tool_message(message, tool_calls: list) -> dict:
    serialized = []
    for index, call in enumerate(tool_calls):
        name, payload = _tool_call_name_and_args(call)
        serialized.append(
            {
                "id": _tool_call_id(call, index),
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(payload if payload is not None else {}),
                },
            }
        )
    content = getattr(message, "content", None)
    if isinstance(message, dict):
        content = message.get("content")
    return {
        "role": "assistant",
        "content": content or "",
        "tool_calls": serialized,
    }


def execute_patch_tool(
    name: str,
    arguments: dict | None,
    files: dict[str, str],
) -> str:
    if name == "read_file":
        if not isinstance(arguments, dict):
            return "error: invalid tool arguments"
        if "path" not in arguments:
            return "error: path is required"
        path = arguments["path"]
        if not isinstance(path, str):
            return "error: path must be a string"
        return run_read_file_tool(files, path)
    if name == "search_code":
        if not isinstance(arguments, dict):
            return "error: invalid tool arguments"
        if "pattern" not in arguments:
            return "error: pattern is required"
        pattern = arguments["pattern"]
        if not isinstance(pattern, str):
            return "error: pattern must be a string"
        return run_search_code_tool(files, pattern)
    return "error: unknown tool"


def usage_tokens_from_response(response) -> int | None:
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return None
    if isinstance(usage, dict):
        total = usage.get("total_tokens")
        if total is not None:
            return int(total)
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
    else:
        total = getattr(usage, "total_tokens", None)
        if total is not None:
            return int(total)
        prompt = getattr(usage, "prompt_tokens", None)
        completion = getattr(usage, "completion_tokens", None)
    if prompt is None and completion is None:
        return None
    return int(prompt or 0) + int(completion or 0)


def normalize_unified_diff(diff: str | None) -> str:
    text = (diff or "").replace("\r\n", "\n").replace("\r", "\n")
    kept: list[str] = []
    for line in text.split("\n"):
        stripped = line.rstrip()
        if stripped.startswith("index "):
            continue
        if stripped.startswith("--- ") or stripped.startswith("+++ "):
            kept.append(stripped.split("\t", 1)[0])
            continue
        kept.append(stripped)
    while kept and kept[-1] == "":
        kept.pop()
    if not kept:
        return ""
    return "\n".join(kept) + "\n"


def diffs_are_identical(left: str | None, right: str | None) -> bool:
    return normalize_unified_diff(left) == normalize_unified_diff(right)


def _is_llm_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    return "timeout" in type(exc).__name__.lower()


def generate_patch(
    *,
    path: str,
    source: str,
    test_source: str,
    stderr: str,
    exception_type: str | None,
    previous_error: str | None = None,
    files: dict[str, str] | None = None,
    diagnosis: str | None = None,
    tokens_used: int = 0,
) -> PatchGenerationResult:
    if not settings.llm_api_key:
        raise LlmNotConfigured("LLM_API_KEY is not set")

    from litellm import completion

    snapshot = _bounded_files(files)
    diagnosis_text = _clip_diagnosis(diagnosis)
    test_source = sanitize_log_text(test_source or "")
    stderr = sanitize_log_text(stderr or "")
    previous_error = sanitize_log_text(previous_error or "")
    source = sanitize_log_text(source or "")
    prompt = (
        "You are AutoPatch Engine. Return ONLY a unified git diff that "
        "fixes the bug. Do not wrap in markdown.\n\n"
        f"File: {path}\n"
        f"Exception: {exception_type}\n"
        f"Test:\n{test_source}\n\n"
        f"Stderr:\n{stderr}\n\n"
        f"Previous error:\n{previous_error}\n\n"
    )
    if diagnosis_text:
        prompt += f"Diagnosis:\n{diagnosis_text}\n\n"
    prompt += f"Current source:\n{source}\n"
    if snapshot:
        prompt += (
            "\nYou may call read_file(path) and search_code(pattern) on the "
            "cloned repository snapshot for additional context. After any tool "
            "use, the final answer must still be only a unified git diff.\n"
        )

    model = _litellm_chat_model(settings.llm_model)
    messages: list[dict] = [{"role": "user", "content": prompt}]
    tool_rounds = 0
    reported = 0
    saw_usage = False
    spent = max(int(tokens_used or 0), 0)
    budget = int(settings.llm_token_budget or 0)
    timeout = settings.llm_timeout_seconds

    while True:
        if budget > 0 and spent >= budget:
            raise LlmTokenBudgetExceeded("LLM token budget exceeded")
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "api_key": settings.llm_api_key,
            "timeout": timeout,
        }
        if settings.llm_api_base and not model.startswith("gemini/"):
            kwargs["api_base"] = settings.llm_api_base
        offer_tools = bool(snapshot) and tool_rounds < MAX_PATCH_TOOL_ROUNDS
        if offer_tools:
            kwargs["tools"] = _PATCH_TOOLS
            kwargs["tool_choice"] = "auto"

        try:
            response = completion(**kwargs)
        except Exception as exc:
            if _is_llm_timeout(exc):
                raise LlmRequestTimeout("LLM request timed out") from exc
            raise
        usage = usage_tokens_from_response(response)
        if usage is not None:
            saw_usage = True
            reported += usage
            spent = max(int(tokens_used or 0), 0) + reported
        message = response.choices[0].message
        tool_calls = _tool_calls_from_message(message)
        if tool_calls:
            if tool_rounds >= MAX_PATCH_TOOL_ROUNDS:
                raise ValueError(
                    "patch generation exceeded "
                    f"{MAX_PATCH_TOOL_ROUNDS} tool rounds"
                )
            if budget > 0 and spent >= budget:
                raise LlmTokenBudgetExceeded("LLM token budget exceeded")
            tool_rounds += 1
            logger.info(
                "patch tool round %s/%s count=%s",
                tool_rounds,
                MAX_PATCH_TOOL_ROUNDS,
                len(tool_calls),
            )
            messages.append(_assistant_tool_message(message, tool_calls))
            for index, call in enumerate(tool_calls):
                name, payload = _tool_call_name_and_args(call)
                result = execute_patch_tool(name, payload, snapshot)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": _tool_call_id(call, index),
                        "content": result,
                    }
                )
            continue

        content = getattr(message, "content", None)
        if isinstance(message, dict):
            content = message.get("content")
        return PatchGenerationResult(
            diff=_extract_unified_diff(content or ""),
            tokens_used=reported if saw_usage else None,
        )
