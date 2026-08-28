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
