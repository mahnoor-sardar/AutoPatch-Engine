from types import SimpleNamespace

from app.services.e2b_runner import MAX_FILES
from app.services.patcher import (
    MAX_DIAGNOSIS_CHARS,
    MAX_PATCH_TOOL_ROUNDS,
    MAX_SEARCH_HITS,
    MAX_SEARCH_PATTERN_CHARS,
    MAX_TOOL_OUTPUT_CHARS,
    execute_patch_tool,
    generate_patch,
    run_read_file_tool,
    run_search_code_tool,
)


FILES = {
    "app/math.py": "def calculate():\n    return 1 / 0\n",
    "app/util.py": "def helper():\n    return calculate()\n",
}

VALID_DIFF = "diff --git a/app/math.py b/app/math.py\n--- a/app/math.py\n+++ b/app/math.py\n"


def _message(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _completion(message):
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _tool_call(name, arguments, call_id="call_1"):
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _enable_llm(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "test-key")


def test_read_file_returns_snapshot_contents():
    result = run_read_file_tool(FILES, "app/math.py")
    assert "return 1 / 0" in result
    assert not result.startswith("error:")


def test_read_file_rejects_unknown_path():
    result = run_read_file_tool(FILES, "app/missing.py")
    assert result == "error: file not found in repository snapshot"


def test_read_file_rejects_absolute_paths():
    assert run_read_file_tool(FILES, "/etc/passwd").startswith(
        "error: absolute paths are not allowed"
    )
    assert run_read_file_tool(FILES, "C:/Windows/system.ini").startswith(
        "error: absolute paths are not allowed"
    )


def test_read_file_rejects_parent_traversal():
    result = run_read_file_tool(FILES, "../app/math.py")
    assert result == "error: path traversal is not allowed"
    nested = run_read_file_tool(FILES, "app/../../etc/passwd")
    assert nested == "error: path traversal is not allowed"


def test_search_code_only_uses_in_memory_map(tmp_path):
    leaked = tmp_path / "secret.py"
    leaked.write_text("UNIQUE_WORKER_HOST_TOKEN_XYZ", encoding="utf-8")
    result = run_search_code_tool(FILES, "calculate")
    assert "app/math.py:" in result
    assert "app/util.py:" in result
    assert "UNIQUE_WORKER_HOST_TOKEN_XYZ" not in result
    assert "secret.py" not in result


def test_tool_output_is_clipped():
    huge = {"big.py": "A" * (MAX_TOOL_OUTPUT_CHARS + 5000)}
    result = run_read_file_tool(huge, "big.py")
    assert result.endswith("...[truncated]")
    assert len(result) <= MAX_TOOL_OUTPUT_CHARS + len("\n...[truncated]")


def test_generate_patch_tool_round_then_unified_diff(monkeypatch):
    _enable_llm(monkeypatch)
    seen = []

    def fake_completion(**kwargs):
        seen.append(kwargs)
        if len(seen) == 1:
            assert kwargs.get("tools")
            return _completion(
                _message(
                    tool_calls=[
                        _tool_call("read_file", '{"path": "app/util.py"}'),
                    ]
                )
            )
        assert "tools" in kwargs
        tool_messages = [m for m in kwargs["messages"] if m.get("role") == "tool"]
        assert tool_messages
        assert "helper" in tool_messages[0]["content"]
        return _completion(_message(content=VALID_DIFF))

    monkeypatch.setattr("litellm.completion", fake_completion)
    diff = generate_patch(
        path="app/math.py",
        source=FILES["app/math.py"],
        test_source="def test(): pass",
        stderr="ZeroDivisionError",
        exception_type="ZeroDivisionError",
        files=FILES,
    )
    assert diff.diff == VALID_DIFF
    assert len(seen) == 2


def test_generate_patch_tool_round_limit(monkeypatch):
    _enable_llm(monkeypatch)
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return _completion(
            _message(
                tool_calls=[
                    _tool_call("read_file", '{"path": "app/math.py"}', f"c{len(calls)}"),
                ]
            )
        )

    monkeypatch.setattr("litellm.completion", fake_completion)
    try:
        generate_patch(
            path="app/math.py",
            source=FILES["app/math.py"],
            test_source="def test(): pass",
            stderr="ZeroDivisionError",
            exception_type="ZeroDivisionError",
            files=FILES,
        )
    except ValueError as exc:
        assert "tool rounds" in str(exc)
        assert str(MAX_PATCH_TOOL_ROUNDS) in str(exc)
    else:
        raise AssertionError("expected tool-round limit error")
    assert len(calls) == MAX_PATCH_TOOL_ROUNDS + 1
    assert "tools" not in calls[-1]


def test_generate_patch_invalid_final_content_still_fails(monkeypatch):
    _enable_llm(monkeypatch)

    def fake_completion(**kwargs):
        if kwargs.get("tools"):
            return _completion(
                _message(
                    tool_calls=[_tool_call("search_code", '{"pattern": "calculate"}')]
                )
            )
        return _completion(_message(content="I fixed it in prose."))

    monkeypatch.setattr("litellm.completion", fake_completion)
    try:
        generate_patch(
            path="app/math.py",
            source=FILES["app/math.py"],
            test_source="def test(): pass",
            stderr="ZeroDivisionError",
            exception_type="ZeroDivisionError",
            files=FILES,
        )
    except ValueError as exc:
        assert "unified diff" in str(exc)
    else:
        raise AssertionError("expected unified diff validation to fail")


def test_generate_patch_without_files_does_not_offer_tools(monkeypatch):
    _enable_llm(monkeypatch)
    seen = []

    def fake_completion(**kwargs):
        seen.append(kwargs)
        return _completion(_message(content=VALID_DIFF))

    monkeypatch.setattr("litellm.completion", fake_completion)
    generate_patch(
        path="app/math.py",
        source=FILES["app/math.py"],
        test_source="def test(): pass",
        stderr="boom",
        exception_type="ValueError",
    )
    assert "tools" not in seen[0]
    prompt = seen[0]["messages"][0]["content"]
    assert "Diagnosis:" not in prompt


def test_generate_patch_includes_clipped_sanitized_diagnosis(monkeypatch):
    _enable_llm(monkeypatch)
    seen = []

    def fake_completion(**kwargs):
        seen.append(kwargs)
        return _completion(_message(content=VALID_DIFF))

    monkeypatch.setattr("litellm.completion", fake_completion)
    secret = "api_key=super-secret-value"
    diagnosis = secret + "\n" + ("root cause " * 3000)
    generate_patch(
        path="app/math.py",
        source=FILES["app/math.py"],
        test_source="def test(): pass",
        stderr="boom",
        exception_type="ValueError",
        diagnosis=diagnosis,
    )
    prompt = seen[0]["messages"][0]["content"]
    assert "Diagnosis:" in prompt
    assert "super-secret-value" not in prompt
    assert "[REDACTED]" in prompt
    block = prompt.split("Diagnosis:\n", 1)[1].split("\n\nCurrent source:", 1)[0]
    assert "...[truncated]" in block
    assert len(block) <= MAX_DIAGNOSIS_CHARS + len("\n...[truncated]")
    assert "Current source:" in prompt
    assert "tools" not in seen[0]


def test_read_file_sanitizes_secrets():
    files = {"app/secrets.py": "api_key=super-secret-value\n"}
    result = run_read_file_tool(files, "app/secrets.py")
    assert "super-secret-value" not in result
    assert "[REDACTED]" in result


def test_read_file_rejects_unc_and_file_urls():
    files = {"app/math.py": "x = 1\n"}
    for path in (
        "//server/share/math.py",
        r"\\server\share\math.py",
        "file:///etc/passwd",
        "file://C:/Windows/system.ini",
        r"\\?\C:\Windows\system.ini",
    ):
        result = run_read_file_tool(files, path)
        assert result.startswith("error: absolute paths are not allowed"), path


def test_malformed_tool_arguments_fail_safely(monkeypatch):
    _enable_llm(monkeypatch)
    seen = []

    def fake_completion(**kwargs):
        seen.append(kwargs)
        if len(seen) == 1:
            return _completion(
                _message(
                    tool_calls=[
                        _tool_call("read_file", "not-json"),
                        _tool_call("read_file", '{"path": ["app/math.py"]}'),
                        _tool_call("search_code", "{}"),
                        _tool_call("shell", '{"cmd": "id"}'),
                    ]
                )
            )
        contents = [
            m["content"]
            for m in kwargs["messages"]
            if m.get("role") == "tool"
        ]
        assert contents[0] == "error: invalid tool arguments"
        assert contents[1] == "error: path must be a string"
        assert contents[2] == "error: pattern is required"
        assert contents[3] == "error: unknown tool"
        return _completion(_message(content=VALID_DIFF))

    monkeypatch.setattr("litellm.completion", fake_completion)
    diff = generate_patch(
        path="app/math.py",
        source=FILES["app/math.py"],
        test_source="def test(): pass",
        stderr="boom",
        exception_type="ValueError",
        files=FILES,
    )
    assert diff.diff == VALID_DIFF


def test_execute_patch_tool_rejects_wrong_types():
    assert execute_patch_tool("read_file", None, FILES).startswith("error:")
    assert execute_patch_tool("read_file", {"path": 1}, FILES) == (
        "error: path must be a string"
    )
    assert execute_patch_tool("search_code", {"pattern": 1}, FILES) == (
        "error: pattern must be a string"
    )
    assert execute_patch_tool("search_code", {}, FILES) == (
        "error: pattern is required"
    )


def test_nested_quantifier_is_rejected_quickly():
    import time

    files = {"a.py": "a" * 400 + "\n"}
    started = time.monotonic()
    result = run_search_code_tool(files, "(a+)+b")
    elapsed = time.monotonic() - started
    assert result.startswith("error:")
    assert "nested quantifiers" in result
    assert elapsed < 0.25


def test_large_repetition_and_long_pattern_rejected():
    assert "too large" in run_search_code_tool(FILES, "a{999}")
    assert "too long" in run_search_code_tool(
        FILES, "a" * (MAX_SEARCH_PATTERN_CHARS + 1)
    )


def test_search_hits_are_bounded():
    files = {
        "many.py": "\n".join(f"token {i}" for i in range(MAX_SEARCH_HITS + 25))
    }
    result = run_search_code_tool(files, "token")
    lines = [line for line in result.splitlines() if line.startswith("many.py:")]
    assert len(lines) == MAX_SEARCH_HITS
    assert "further matches omitted" in result


def test_search_deadline_returns_timeout(monkeypatch):
    monkeypatch.setattr("app.services.patcher.SEARCH_TIMEOUT_SECONDS", -1)
    result = run_search_code_tool(FILES, "calculate")
    assert result == "error: search timed out"


def test_search_and_read_do_not_touch_filesystem(monkeypatch, tmp_path):
    leaked = tmp_path / "disk.py"
    leaked.write_text("DISK_ONLY_TOKEN", encoding="utf-8")
    opened = []
    real_open = open

    def guarded_open(*args, **kwargs):
        opened.append(args[0] if args else kwargs.get("file"))
        return real_open(*args, **kwargs)

    monkeypatch.setattr("builtins.open", guarded_open)
    read = run_read_file_tool(FILES, "app/math.py")
    search = run_search_code_tool(FILES, "calculate")
    assert "return 1 / 0" in read
    assert "app/math.py" in search
    assert "DISK_ONLY_TOKEN" not in search
    assert opened == []


def test_snapshot_file_cap_hides_overflow_paths():
    files = {f"f{i}.py": f"n{i}=1\n" for i in range(MAX_FILES + 5)}
    overflow = f"f{MAX_FILES}.py"
    assert overflow in files
    assert run_read_file_tool(files, overflow) == (
        "error: file not found in repository snapshot"
    )
    assert "n0=1" in run_read_file_tool(files, "f0.py")


def test_search_redacts_secrets():
    files = {"cfg.py": "api_key=super-secret-value\n"}
    result = run_search_code_tool(files, "api_key")
    assert "super-secret-value" not in result
    assert "[REDACTED]" in result
