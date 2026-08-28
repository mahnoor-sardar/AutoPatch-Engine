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


def test_synthesize_python_repro_incomplete_for_untyped_required_params():
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
    with pytest.raises(ValueError, match="incomplete"):
        synthesize_python_repro(
            location=location,
            source=source,
            exception_type="TypeError",
            message="unsupported",
        )


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
