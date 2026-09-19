from types import SimpleNamespace

from app.services.harness import ReproductionResult, run_reproduction_test


def test_missing_expected_exception_is_not_reproduced():
    result = ReproductionResult(
        exit_code=1,
        stdout="",
        stderr="ERROR collecting tests/autopatch_repro_test.py",
        expected_exception=None,
    )
    assert result.reproduced is False


def test_missing_expected_exception_timeout_is_not_reproduced():
    result = ReproductionResult(
        exit_code=1,
        stdout="",
        stderr="TimeoutError: command timed out after 120s",
        expected_exception=None,
    )
    assert result.reproduced is False


def test_generic_expected_exception_is_not_reproduced():
    result = ReproductionResult(
        exit_code=1,
        stdout="",
        stderr="Exception: boom",
        expected_exception="Exception",
    )
    assert result.reproduced is False


def test_p05_collection_error_with_incidental_name_is_not_reproduced():
    result = ReproductionResult(
        exit_code=1,
        stdout=(
            "ERROR collecting tests/autopatch_repro_test.py\n"
            "plugin crashed while handling ZeroDivisionError\n"
            "expected_exception = ZeroDivisionError\n"
        ),
        stderr="INTERNALERROR> plugin failed",
        expected_exception="ZeroDivisionError",
    )
    assert result.reproduced is False


def test_p06_timeout_without_exception_header_is_not_reproduced():
    result = ReproductionResult(
        exit_code=1,
        stdout="",
        stderr="command timed out after 120 seconds",
        expected_exception="ZeroDivisionError",
    )
    assert result.reproduced is False


def test_return_path_missing_argument_typeerror_is_not_reproduced():
    sandbox = SimpleNamespace(
        write_file=lambda path, content: None,
        run=lambda command, timeout=30: SimpleNamespace(
            stdout="FAILED tests/autopatch_repro_test.py",
            stderr="TypeError: add() missing 2 required positional arguments: 'a' and 'b'",
            exit_code=1,
        ),
    )
    result = run_reproduction_test(
        sandbox,
        "tests/autopatch_repro_test.py",
        "def test_reproduces_add_failure():\n"
        "    expected_exception = TypeError\n",
        install_dependencies=False,
    )
    assert result.synthesis_failed is True
    assert result.expected_exception == "TypeError"
    assert result.reproduced is False


def test_real_python_exception_header_is_reproduced():
    result = ReproductionResult(
        exit_code=1,
        stdout="",
        stderr="ZeroDivisionError: division by zero",
        expected_exception="ZeroDivisionError",
    )
    assert result.reproduced is True
    assert result.passed_clean is False


def test_pytest_exception_line_is_reproduced():
    result = ReproductionResult(
        exit_code=1,
        stdout="E   ZeroDivisionError: division by zero",
        stderr="",
        expected_exception="ZeroDivisionError",
    )
    assert result.reproduced is True
    assert result.passed_clean is False


def test_real_js_exception_header_is_reproduced():
    result = ReproductionResult(
        exit_code=1,
        stdout="not ok 1 - reproduces getUser failure",
        stderr="TypeError: Cannot read properties of undefined",
        expected_exception="TypeError",
    )
    assert result.reproduced is True
    assert result.passed_clean is False


def test_incidental_exception_name_is_not_reproduced():
    result = ReproductionResult(
        exit_code=1,
        stdout="FAILED tests/test_zero_division[ZeroDivisionError]",
        stderr="expected_exception = ZeroDivisionError",
        expected_exception="ZeroDivisionError",
    )
    assert result.reproduced is False
