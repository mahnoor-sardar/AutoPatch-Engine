from app.services.diagnostic import (
    DiagnosticLocation,
    locate_frames,
)
from app.services.stacktrace import StackFrame


def test_locate_exact_function():
    frames = [
        StackFrame(
            file="backend/app/services/math.py",
            line=8,
            function="calculate",
        )
    ]

    symbols = [
        {
            "path": "backend/app/services/math.py",
            "name": "calculate",
            "kind": "function",
            "start_line": 8,
        },
        {
            "path": "backend/app/services/math.py",
            "name": "helper",
            "kind": "function",
            "start_line": 20,
        },
    ]

    results = locate_frames(frames, symbols)

    assert len(results) == 1

    result = results[0]

    assert isinstance(result, DiagnosticLocation)
    assert result.path == "backend/app/services/math.py"
    assert result.name == "calculate"
    assert result.kind == "function"
    assert result.start_line == 8
    assert result.confidence == "high"


def test_locate_nearest_symbol_when_function_name_does_not_match():
    frames = [
        StackFrame(
            file="backend/app/services/math.py",
            line=12,
            function="unknown_function",
        )
    ]

    symbols = [
        {
            "path": "backend/app/services/math.py",
            "name": "calculate",
            "kind": "function",
            "start_line": 8,
        },
        {
            "path": "backend/app/services/math.py",
            "name": "helper",
            "kind": "function",
            "start_line": 20,
        },
    ]

    results = locate_frames(frames, symbols)

    assert len(results) == 1

    result = results[0]

    assert result.path == "backend/app/services/math.py"
    assert result.name == "calculate"
    assert result.start_line == 8
    assert result.confidence == "medium"


def test_unmatched_file_is_not_localized():
    frames = [
        StackFrame(
            file="backend/app/missing.py",
            line=10,
            function="missing",
        )
    ]

    symbols = [
        {
            "path": "backend/app/services/math.py",
            "name": "calculate",
            "kind": "function",
            "start_line": 8,
        }
    ]

    results = locate_frames(frames, symbols)

    assert results == []


def test_multiple_frames_are_localized():
    frames = [
        StackFrame(
            file="backend/app/main.py",
            line=10,
            function="main",
        ),
        StackFrame(
            file="backend/app/services/math.py",
            line=8,
            function="calculate",
        ),
    ]

    symbols = [
        {
            "path": "backend/app/main.py",
            "name": "main",
            "kind": "function",
            "start_line": 5,
        },
        {
            "path": "backend/app/services/math.py",
            "name": "calculate",
            "kind": "function",
            "start_line": 8,
        },
    ]

    results = locate_frames(frames, symbols)

    assert len(results) == 2

    assert results[0].name == "main"
    assert results[0].confidence == "high"

    assert results[1].name == "calculate"
    assert results[1].confidence == "high"