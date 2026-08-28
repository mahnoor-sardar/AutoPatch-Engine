from types import SimpleNamespace

from app.services.harness import ReproductionResult, run_reproduction_test


def test_reproduction_result_success_when_exit_code_is_nonzero():
    result = ReproductionResult(
        exit_code=1,
        stdout="",
        stderr="ZeroDivisionError: division by zero",
    )
    assert result.reproduced is True
    assert result.exit_code == 1


def test_reproduction_result_not_reproduced_when_exit_code_is_zero():
    result = ReproductionResult(
        exit_code=0,
        stdout="1 passed",
        stderr="",
    )
    assert result.reproduced is False
    assert result.exit_code == 0


def test_setup_failure_is_not_reproduced():
    result = ReproductionResult(
        exit_code=1,
        stdout="",
        stderr="Could not install packages",
        setup_failed=True,
    )
    assert result.reproduced is False


def test_missing_argument_typeerror_is_not_reproduced():
    result = ReproductionResult(
        exit_code=1,
        stdout="",
        stderr="TypeError: add() missing 2 required positional arguments",
        synthesis_failed=True,
    )
    assert result.reproduced is False


def test_dummy_none_typeerror_is_not_zero_division_reproduction():
    result = ReproductionResult(
        exit_code=1,
        stdout="",
        stderr=(
            "TypeError: unsupported operand type(s) for +: "
            "'NoneType' and 'NoneType'"
        ),
        expected_exception="ZeroDivisionError",
    )
    assert result.reproduced is False


def test_expected_exception_in_stderr_is_reproduced():
    result = ReproductionResult(
        exit_code=1,
        stdout="",
        stderr="ZeroDivisionError: division by zero",
        expected_exception="ZeroDivisionError",
    )
    assert result.reproduced is True


def test_run_reproduction_rejects_none_add_typeerror_for_zero_division(
    monkeypatch,
):
    def fake_install(sandbox):
        return (0, "installed", "")

    monkeypatch.setattr(
        "app.services.harness.install_project_dependencies",
        fake_install,
    )

    class CommandFailed(Exception):
        exit_code = 1
        stdout = ""
        stderr = (
            "TypeError: unsupported operand type(s) for +: "
            "'NoneType' and 'NoneType'"
        )

    def boom(command, timeout=30):
        raise CommandFailed()

    sandbox = SimpleNamespace(
        write_file=lambda path, content: None,
        run=boom,
    )
    test_source = """
def test_reproduces_add_failure():
    expected_exception = ZeroDivisionError
    add(None, None)
"""
    result = run_reproduction_test(
        sandbox,
        "tests/autopatch_repro_test.py",
        test_source,
        install_dependencies=False,
    )
    assert result.synthesis_failed is False
    assert result.expected_exception == "ZeroDivisionError"
    assert result.reproduced is False


def test_reproduction_skips_install_when_requested(monkeypatch):
    installs = []

    def fake_install(sandbox):
        installs.append(sandbox)
        return (0, "installed", "")

    monkeypatch.setattr(
        "app.services.harness.install_project_dependencies",
        fake_install,
    )
    sandbox = SimpleNamespace(
        write_file=lambda path, content: None,
        run=lambda command, timeout=30: SimpleNamespace(
            stdout="1 failed",
            stderr="ZeroDivisionError",
            exit_code=1,
        ),
    )
    try:
        run_reproduction_test(
            sandbox,
            "tests/test_repro.py",
            "def test():\n    assert False\n",
            install_dependencies=False,
        )
    except Exception:
        pass
    assert installs == []

    run_reproduction_test(
        sandbox,
        "tests/test_repro.py",
        "def test():\n    assert False\n",
        install_dependencies=True,
    )
    assert len(installs) == 1
