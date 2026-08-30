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
    assert "Math.divide(None, 0, 0)" in result.test_source
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
    assert "fn(undefined, undefined)" in result.test_source
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
    assert "fn(undefined)" in result.test_source
