from app.services.stacktrace import parse_stack_trace


def test_parse_python_traceback():
    trace = """Traceback (most recent call last):
  File "app/services/user.py", line 42, in get_user
    return user.name
AttributeError: 'NoneType' object has no attribute 'name'
"""

    result = parse_stack_trace(trace)

    assert result.exception_type == "AttributeError"
    assert result.message == "'NoneType' object has no attribute 'name'"
    assert len(result.frames) == 1

    frame = result.frames[0]

    assert frame.file == "app/services/user.py"
    assert frame.line == 42
    assert frame.function == "get_user"


def test_parse_multiple_python_frames():
    trace = """Traceback (most recent call last):
  File "app/main.py", line 10, in main
    process()
  File "app/services/processor.py", line 25, in process
    return calculate()
  File "app/services/math.py", line 8, in calculate
    return 10 / 0
ZeroDivisionError: division by zero
"""

    result = parse_stack_trace(trace)

    assert result.exception_type == "ZeroDivisionError"
    assert result.message == "division by zero"
    assert len(result.frames) == 3

    assert result.frames[0].file == "app/main.py"
    assert result.frames[0].line == 10
    assert result.frames[0].function == "main"

    assert result.frames[2].file == "app/services/math.py"
    assert result.frames[2].line == 8
    assert result.frames[2].function == "calculate"


def test_invalid_trace_returns_empty_result():
    result = parse_stack_trace("This is not a Python traceback")

    assert result.exception_type is None
    assert result.message is None
    assert result.frames == []