from pathlib import Path

import pytest

from app.services.diagnostic import DiagnosticLocation
from app.services.repro import synthesize_javascript_repro, synthesize_python_repro


def test_synthesize_python_repro():
    location = DiagnosticLocation(
        path="app/services/math.py",
        name="calculate",
        kind="function",
        start_line=8,
        confidence="high",
    )

    source = """def calculate():
    return 10 / 0
"""

    result = synthesize_python_repro(
        location=location,
        source=source,
        exception_type="ZeroDivisionError",
        message="division by zero",
    )

    assert result.test_path == "tests/autopatch_repro_test.py"
    assert "def test_reproduces_calculate_failure" in result.test_source
    assert "ZeroDivisionError" in result.test_source
    assert "calculate()" in result.test_source
    assert "except expected_exception" in result.test_source
    assert "except Exception:\n        return" not in result.test_source


def test_synthesize_python_repro_uses_parameter_defaults():
    location = DiagnosticLocation(
        path="app/services/math.py",
        name="greet",
        kind="function",
        start_line=1,
        confidence="high",
    )
    source = '''def greet(name="world", times=1):
    return name * times
'''
    result = synthesize_python_repro(
        location=location,
        source=source,
        exception_type="TypeError",
        message="unsupported",
    )
    assert 'greet("world", 1)' in result.test_source
    assert "None" not in result.test_source.split("greet(", 1)[1].split(")", 1)[0]


def test_synthesize_python_repro_uses_primitive_annotations():
    location = DiagnosticLocation(
        path="app/services/math.py",
        name="add",
        kind="function",
        start_line=1,
        confidence="high",
    )
    source = """def add(a: int, b: float, c: str, d: bool):
    return a
"""
    result = synthesize_python_repro(
        location=location,
        source=source,
        exception_type="TypeError",
        message="unsupported",
    )
    assert 'add(0, 0.0, "", False)' in result.test_source


def test_synthesize_python_repro_required_untyped_params_use_exception_dummy():
    location = DiagnosticLocation(
        path="app/services/math.py",
        name="calculate",
        kind="function",
        start_line=1,
        confidence="high",
    )
    source = """def calculate(x, y):
    return x / y
"""
    result = synthesize_python_repro(
        location=location,
        source=source,
        exception_type="ZeroDivisionError",
        message="division by zero",
    )
    assert "calculate(0, 0)" in result.test_source
    ns = {}
    exec(source, ns)
    try:
        ns["calculate"](0, 0)
    except ZeroDivisionError:
        pass
    else:
        raise AssertionError("dummy 0, 0 must still raise ZeroDivisionError")


def test_synthesize_python_repro_untyped_typeerror_uses_none():
    location = DiagnosticLocation(
        path="app/services/math.py",
        name="add",
        kind="function",
        start_line=1,
        confidence="high",
    )
    source = """def add(a, b):
    return a + b
"""
    result = synthesize_python_repro(
        location=location,
        source=source,
        exception_type="TypeError",
        message="unsupported operand type(s)",
    )
    assert "add(None, None)" in result.test_source


def test_synthesize_python_repro_method_skips_self_and_uses_owner():
    location = DiagnosticLocation(
        path="app/services/math.py",
        name="divide",
        kind="method",
        start_line=2,
        confidence="high",
    )
    source = """class Math:
    def divide(self, x, y):
        return x / y
"""
    result = synthesize_python_repro(
        location=location,
        source=source,
        exception_type="ZeroDivisionError",
        message="division by zero",
    )
    assert "from app.services.math import Math" in result.test_source
    assert "Math().divide(0, 0)" in result.test_source
    assert "Math.divide(None" not in result.test_source
    assert "divide(None" not in result.test_source
    assert "divide()" not in result.test_source.split("try:", 1)[1]


def test_synthesize_python_repro_incomplete_for_complex_required_params():
    location = DiagnosticLocation(
        path="app/services/math.py",
        name="handle",
        kind="function",
        start_line=1,
        confidence="high",
    )
    source = """def handle(user: User):
    return user
"""
    with pytest.raises(ValueError, match="incomplete"):
        synthesize_python_repro(
            location=location,
            source=source,
            exception_type="AttributeError",
            message="missing",
        )


def test_synthesize_repro_rejects_non_python_file():
    location = DiagnosticLocation(
        path="app/services/math.ts",
        name="calculate",
        kind="function",
        start_line=8,
        confidence="high",
    )

    source = "function calculate() { return 1 / 0; }"

    try:
        synthesize_python_repro(
            location=location,
            source=source,
            exception_type="Error",
            message="failure",
        )
    except ValueError as exc:
        assert "Python" in str(exc)
    else:
        raise AssertionError(
            "Expected ValueError for non-Python source"
        )


def test_synthesize_javascript_repro_uses_dummy_args_and_esm():
    location = DiagnosticLocation(
        path="src/math.ts",
        name="add",
        kind="function",
        start_line=1,
        confidence="high",
    )
    source = "export function add(a: number, b: number) { return a + b }"
    result = synthesize_javascript_repro(
        location=location,
        source=source,
        exception_type="Error",
        message="fail",
    )
    assert result.test_path.endswith(".ts")
    assert "undefined, undefined" in result.test_source
    assert "import(" in result.test_source
    assert "node:test" in result.test_source
    assert "assert.throws" not in result.test_source
    assert "await Promise.resolve(fn(undefined, undefined))" in result.test_source
    assert "const expected_exception = Error" not in result.test_source


def test_synthesize_javascript_repro_embeds_specific_error_type():
    location = DiagnosticLocation(
        path="src/user.js",
        name="getUser",
        kind="function",
        start_line=1,
        confidence="high",
    )
    source = "export function getUser(id) { return id.missing }"
    result = synthesize_javascript_repro(
        location=location,
        source=source,
        exception_type="TypeError",
        message="Cannot read properties of undefined",
    )
    assert result.test_path.endswith(".mjs")
    assert "const expected_exception = TypeError;" in result.test_source
    assert "assert.throws" not in result.test_source
    assert "assert.rejects" not in result.test_source
    assert "await Promise.resolve(fn(undefined))" in result.test_source


def test_synthesize_python_repro_consumes_awaitable():
    location = DiagnosticLocation(
        path="app/services/math.py",
        name="boom",
        kind="function",
        start_line=1,
        confidence="high",
    )
    source = """async def boom():
    raise ZeroDivisionError("division by zero")
"""
    result = synthesize_python_repro(
        location=location,
        source=source,
        exception_type="ZeroDivisionError",
        message="division by zero",
    )
    assert "import inspect" in result.test_source
    assert "import asyncio" in result.test_source
    assert "_result = boom()" in result.test_source
    assert "inspect.isawaitable(_result)" in result.test_source
    assert "asyncio.run(_result)" in result.test_source
    assert "pytest.raises" not in result.test_source


def test_p18_generated_repro_executes_async_body(monkeypatch):
    location = DiagnosticLocation(
        path="pkg/mod.py",
        name="boom",
        kind="function",
        start_line=1,
        confidence="high",
    )
    source = """async def boom():
    raise ZeroDivisionError("division by zero")
"""
    result = synthesize_python_repro(
        location=location,
        source=source,
        exception_type="ZeroDivisionError",
        message="division by zero",
    )
    assert "inspect.isawaitable(_result)" in result.test_source
    assert "asyncio.run(_result)" in result.test_source
    assert "pytest.raises" not in result.test_source

    import sys
    import types
    import warnings

    mod = types.ModuleType("pkg.mod")
    pkg = types.ModuleType("pkg")
    pkg.mod = mod
    exec(compile(source, "mod.py", "exec"), mod.__dict__)
    monkeypatch.setitem(sys.modules, "pkg", pkg)
    monkeypatch.setitem(sys.modules, "pkg.mod", mod)

    ns: dict = {
        "__name__": "generated_repro",
        "__file__": str(Path("tests/autopatch_repro_test.py").resolve()),
    }
    exec(compile(result.test_source, "generated_repro.py", "exec"), ns)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            ns["test_reproduces_boom_failure"]()
        except ZeroDivisionError:
            pass
        else:
            raise AssertionError(
                "awaited async body must surface ZeroDivisionError"
            )
    messages = " ".join(str(item.message).lower() for item in caught)
    assert "never awaited" not in messages


def test_synthesize_python_repro_sync_still_calls_directly():
    location = DiagnosticLocation(
        path="app/services/math.py",
        name="calculate",
        kind="function",
        start_line=1,
        confidence="high",
    )
    source = """def calculate():
    return 10 / 0
"""
    result = synthesize_python_repro(
        location=location,
        source=source,
        exception_type="ZeroDivisionError",
        message="division by zero",
    )
    assert "_result = calculate()" in result.test_source
    assert "inspect.isawaitable(_result)" in result.test_source
    ns = {}
    exec(source, ns)
    import asyncio
    import inspect

    try:
        _result = ns["calculate"]()
        if inspect.isawaitable(_result):
            asyncio.run(_result)
    except ZeroDivisionError:
        pass
    else:
        raise AssertionError("sync target must still raise ZeroDivisionError")


def test_synthesize_python_repro_constructs_instance_with_init_args():
    location = DiagnosticLocation(
        path="app/services/math.py",
        name="divide",
        kind="method",
        start_line=4,
        confidence="high",
    )
    source = """class Math:
    def __init__(self, scale: int):
        self.scale = scale

    def divide(self, x, y):
        return x / y
"""
    result = synthesize_python_repro(
        location=location,
        source=source,
        exception_type="ZeroDivisionError",
        message="division by zero",
    )
    assert "Math(0).divide(0, 0)" in result.test_source
    assert "Math.divide(None" not in result.test_source


def test_synthesize_python_repro_init_keyword_only_args():
    location = DiagnosticLocation(
        path="app/services/math.py",
        name="divide",
        kind="method",
        start_line=4,
        confidence="high",
    )
    source = """class Math:
    def __init__(self, *, scale: int = 1):
        self.scale = scale

    def divide(self, x, y):
        return x / y
"""
    result = synthesize_python_repro(
        location=location,
        source=source,
        exception_type="ZeroDivisionError",
        message="division by zero",
    )
    assert "Math(scale=1).divide(0, 0)" in result.test_source


def test_synthesize_python_repro_unconstructable_init_is_incomplete():
    location = DiagnosticLocation(
        path="app/services/math.py",
        name="divide",
        kind="method",
        start_line=4,
        confidence="high",
    )
    source = """class Math:
    def __init__(self, user: User):
        self.user = user

    def divide(self, x, y):
        return x / y
"""
    with pytest.raises(ValueError, match="incomplete"):
        synthesize_python_repro(
            location=location,
            source=source,
            exception_type="ZeroDivisionError",
            message="division by zero",
        )


def test_synthesize_python_repro_keyword_only_args():
    location = DiagnosticLocation(
        path="app/services/math.py",
        name="divide",
        kind="function",
        start_line=1,
        confidence="high",
    )
    source = """def divide(a, *, b):
    return a / b
"""
    result = synthesize_python_repro(
        location=location,
        source=source,
        exception_type="ZeroDivisionError",
        message="division by zero",
    )
    assert "divide(0, b=0)" in result.test_source
    assert "divide(0, 0)" not in result.test_source


def test_synthesize_python_repro_positional_only_args():
    location = DiagnosticLocation(
        path="app/services/math.py",
        name="divide",
        kind="function",
        start_line=1,
        confidence="high",
    )
    source = """def divide(a, /, b):
    return a / b
"""
    result = synthesize_python_repro(
        location=location,
        source=source,
        exception_type="ZeroDivisionError",
        message="division by zero",
    )
    assert "divide(0, 0)" in result.test_source
    assert "a=" not in result.test_source
    assert "b=" not in result.test_source.split("divide(", 1)[1]


def test_synthesize_python_repro_classmethod_uses_owner():
    location = DiagnosticLocation(
        path="app/services/math.py",
        name="divide",
        kind="method",
        start_line=2,
        confidence="high",
    )
    source = """class Math:
    @classmethod
    def divide(cls, x, y):
        return x / y
"""
    result = synthesize_python_repro(
        location=location,
        source=source,
        exception_type="ZeroDivisionError",
        message="division by zero",
    )
    assert "from app.services.math import Math" in result.test_source
    assert "Math.divide(0, 0)" in result.test_source
    assert "Math()" not in result.test_source


def test_synthesize_python_repro_staticmethod_uses_owner():
    location = DiagnosticLocation(
        path="app/services/math.py",
        name="divide",
        kind="method",
        start_line=2,
        confidence="high",
    )
    source = """class Math:
    @staticmethod
    def divide(x, y):
        return x / y
"""
    result = synthesize_python_repro(
        location=location,
        source=source,
        exception_type="ZeroDivisionError",
        message="division by zero",
    )
    assert "from app.services.math import Math" in result.test_source
    assert "Math.divide(0, 0)" in result.test_source
    assert "Math()" not in result.test_source


def test_synthesize_javascript_repro_custom_error_uses_global_this():
    location = DiagnosticLocation(
        path="src/user.js",
        name="getUser",
        kind="function",
        start_line=1,
        confidence="high",
    )
    source = "export function getUser(id) { throw new AppError('missing'); }"
    result = synthesize_javascript_repro(
        location=location,
        source=source,
        exception_type="AppError",
        message="missing",
    )
    assert "const expected_exception = globalThis.AppError;" in result.test_source
    assert "const expected_exception = AppError;" not in result.test_source
    assert "assert.throws" not in result.test_source
    assert "assert.rejects" not in result.test_source
    assert "import AppError" not in result.test_source


def test_noop_target_still_passes_without_value_oracle():
    """F13 leftover: a no-op can return cleanly; no semantic oracle is added."""
    source = """def calculate():
    return None
"""
    ns = {}
    exec(source, ns)
    import asyncio
    import inspect

    _result = ns["calculate"]()
    if inspect.isawaitable(_result):
        asyncio.run(_result)
    assert _result is None
