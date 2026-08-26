from types import SimpleNamespace

from app.services.harness import ReproductionResult
from app.services.repro import ReproductionTest


def test_reproduction_pipeline_components():
    from app.services.diagnostic import locate_frames
    from app.services.repro import synthesize_python_repro
    from app.services.stacktrace import parse_stack_trace

    trace = """Traceback (most recent call last):
  File "backend/app/services/math.py", line 2, in calculate
    return 10 / 0
ZeroDivisionError: division by zero
"""

    parsed = parse_stack_trace(trace)

    assert parsed.exception_type == "ZeroDivisionError"
    assert len(parsed.frames) == 1

    symbols = [
        {
            "path": "backend/app/services/math.py",
            "name": "calculate",
            "kind": "function",
            "start_line": 1,
        }
    ]

    locations = locate_frames(
        parsed.frames,
        symbols,
    )

    assert len(locations) == 1

    location = locations[0]

    source = """def calculate():
    return 10 / 0
"""

    reproduction = synthesize_python_repro(
        location=location,
        source=source,
        exception_type=parsed.exception_type,
        message=parsed.message,
    )

    assert isinstance(
        reproduction,
        ReproductionTest,
    )

    assert (
        reproduction.test_path
        == "tests/autopatch_repro_test.py"
    )

    assert "calculate()" in reproduction.test_source
    assert "ZeroDivisionError" in reproduction.test_source

    result = ReproductionResult(
        exit_code=1,
        stdout="",
        stderr="ZeroDivisionError: division by zero",
    )

    assert result.reproduced is True