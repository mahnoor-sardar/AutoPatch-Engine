from app.services.diagnostic import DiagnosticLocation
from app.services.repro import synthesize_python_repro


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