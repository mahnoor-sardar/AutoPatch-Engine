from types import SimpleNamespace

from app.services.harness import (
    ADDITIONAL_TESTS_SKIPPED,
    ReproductionResult,
    extra_suite_merge_message,
    extra_suite_ok,
    relevant_backend_test_files,
    relevant_python_test_files,
    run_full_test_suite,
    run_reproduction_test,
)


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
    assert result.passed_clean is False


def test_no_exception_is_passed_clean_not_reproduced():
    result = ReproductionResult(
        exit_code=0,
        stdout="1 passed",
        stderr="",
        expected_exception="ZeroDivisionError",
    )
    assert result.reproduced is False
    assert result.passed_clean is True


def test_unexpected_exception_is_neither_reproduced_nor_passed_clean():
    result = ReproductionResult(
        exit_code=1,
        stdout="FAILED tests/autopatch_repro_test.py",
        stderr="TypeError: unsupported operand type(s)",
        expected_exception="ZeroDivisionError",
    )
    assert result.reproduced is False
    assert result.passed_clean is False


def test_collection_failure_is_not_passed_clean():
    result = ReproductionResult(
        exit_code=2,
        stdout="",
        stderr="ERROR collecting tests/autopatch_repro_test.py",
        expected_exception="ZeroDivisionError",
    )
    assert result.reproduced is False
    assert result.passed_clean is False


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
    assert result.passed_clean is False


def test_run_reproduction_uses_command_exit_code():
    sandbox = SimpleNamespace(
        write_file=lambda path, content: None,
        run=lambda command, timeout=30: SimpleNamespace(
            stdout="1 passed",
            stderr="",
            exit_code=0,
        ),
    )
    passed = run_reproduction_test(
        sandbox,
        "tests/autopatch_repro_test.py",
        "def test_reproduces_calculate_failure():\n"
        "    expected_exception = ZeroDivisionError\n",
        install_dependencies=False,
    )
    assert passed.exit_code == 0
    assert passed.reproduced is False
    assert passed.passed_clean is True

    failed = run_reproduction_test(
        SimpleNamespace(
            write_file=lambda path, content: None,
            run=lambda command, timeout=30: SimpleNamespace(
                stdout="ERROR collecting tests/autopatch_repro_test.py",
                stderr="ImportError: cannot import name calculate",
                exit_code=2,
            ),
        ),
        "tests/autopatch_repro_test.py",
        "def test_reproduces_calculate_failure():\n"
        "    expected_exception = ZeroDivisionError\n",
        install_dependencies=False,
    )
    assert failed.exit_code == 2
    assert failed.reproduced is False
    assert failed.passed_clean is False


def test_js_expected_error_is_reproduced():
    result = ReproductionResult(
        exit_code=1,
        stdout="not ok 1 - reproduces getUser failure",
        stderr="TypeError: Cannot read properties of undefined",
        expected_exception="TypeError",
    )
    assert result.reproduced is True
    assert result.passed_clean is False


def test_js_no_error_is_passed_clean():
    result = ReproductionResult(
        exit_code=0,
        stdout="ok 1 - reproduces getUser failure",
        stderr="",
        expected_exception="TypeError",
    )
    assert result.reproduced is False
    assert result.passed_clean is True


def test_js_different_error_is_neither_reproduced_nor_passed_clean():
    result = ReproductionResult(
        exit_code=1,
        stdout="not ok 1 - reproduces getUser failure",
        stderr="RangeError: Maximum call stack size exceeded",
        expected_exception="TypeError",
    )
    assert result.reproduced is False
    assert result.passed_clean is False


def test_js_module_load_failure_is_not_passed_clean():
    result = ReproductionResult(
        exit_code=1,
        stdout="",
        stderr="Error [ERR_MODULE_NOT_FOUND]: Cannot find module",
        expected_exception="TypeError",
    )
    assert result.reproduced is False
    assert result.passed_clean is False


def test_js_source_expected_exception_is_parsed():
    sandbox = SimpleNamespace(
        write_file=lambda path, content: None,
        run=lambda command, timeout=30: SimpleNamespace(
            stdout="not ok 1 - reproduces getUser failure",
            stderr="TypeError: Cannot read properties of undefined",
            exit_code=1,
        ),
    )
    result = run_reproduction_test(
        sandbox,
        "tests/autopatch_repro.test.mjs",
        'const expected_exception = TypeError;\n'
        'test("reproduces getUser failure", async () => { fn(); });\n',
        install_dependencies=False,
    )
    assert result.expected_exception == "TypeError"
    assert result.reproduced is True
    assert result.passed_clean is False

    mismatched = run_reproduction_test(
        SimpleNamespace(
            write_file=lambda path, content: None,
            run=lambda command, timeout=30: SimpleNamespace(
                stdout="not ok 1 - reproduces getUser failure",
                stderr="RangeError: Maximum call stack size exceeded",
                exit_code=1,
            ),
        ),
        "tests/autopatch_repro.test.mjs",
        'const expected_exception = TypeError;\n'
        'test("reproduces getUser failure", async () => { fn(); });\n',
        install_dependencies=False,
    )
    assert mismatched.expected_exception == "TypeError"
    assert mismatched.reproduced is False
    assert mismatched.passed_clean is False


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


class _SuiteSandbox:
    def __init__(self, existing, git_stdout="", pytest_exit=0, pytest_stderr=""):
        self.existing = existing
        self.git_stdout = git_stdout
        self.pytest_exit = pytest_exit
        self.pytest_stderr = pytest_stderr
        self.ran = []

    def run(self, command, timeout=30):
        self.ran.append(command)
        if command.startswith("test -e "):
            path = command[len("test -e ") :].split(";", 1)[0].strip()
            code = "0" if path in self.existing else "1"
            return SimpleNamespace(stdout=f"{code}\n", stderr="", exit_code=0)
        if command.startswith("git -C /home/user/repo diff --name-only"):
            return SimpleNamespace(
                stdout=self.git_stdout,
                stderr="",
                exit_code=0,
            )
        if "python -m pytest" in command or "npm test" in command:
            return SimpleNamespace(
                stdout="1 passed" if self.pytest_exit == 0 else "1 failed",
                stderr=self.pytest_stderr,
                exit_code=self.pytest_exit,
            )
        return SimpleNamespace(stdout="1 passed", stderr="", exit_code=0)


def test_relevant_backend_test_files_maps_app_and_tests():
    exists = {"tests/test_harness.py", "tests/test_patcher.py"}
    mapped = relevant_backend_test_files(
        [
            "backend/app/services/harness.py",
            "backend/tests/test_patcher.py",
            "backend/tests/fixtures/sample.py",
            "README.md",
        ],
        test_file_exists=lambda rel: rel in exists,
    )
    assert mapped == ["tests/test_harness.py", "tests/test_patcher.py"]


def test_full_suite_backend_uses_cwd_env_and_relevant_files():
    sandbox = _SuiteSandbox(
        existing={
            "/home/user/repo/backend",
            "/home/user/repo/backend/tests/test_harness.py",
        },
        git_stdout="backend/app/services/harness.py\n",
    )
    result = run_full_test_suite(sandbox)
    assert result.exit_code == 0
    assert result.ran_tests is True
    assert result.skipped is False
    pytest_cmds = [c for c in sandbox.ran if "python -m pytest" in c]
    assert len(pytest_cmds) == 1
    command = pytest_cmds[0]
    assert command.startswith("cd /home/user/repo/backend && ")
    assert "API_KEY=dev-local-key" in command
    assert "GITHUB_WEBHOOK_SECRET=dev-webhook-secret" in command
    assert "tests/test_harness.py" in command
    assert "cd /home/user/repo && python -m pytest -q" not in command
    assert ".env" not in command


def test_full_suite_empty_relevant_tests_skips_pytest():
    sandbox = _SuiteSandbox(
        existing={"/home/user/repo/backend"},
        git_stdout="backend/app/services/missing_module.py\n",
    )
    result = run_full_test_suite(sandbox)
    assert result.exit_code == 0
    assert result.ran_tests is False
    assert result.skipped is True
    assert result.stdout == ADDITIONAL_TESTS_SKIPPED
    assert extra_suite_ok(result) is True
    assert not any("python -m pytest" in c for c in sandbox.ran)
    assert any(
        c.startswith("git -C /home/user/repo diff --name-only")
        for c in sandbox.ran
    )


def test_full_suite_without_backend_keeps_repo_root_pytest():
    sandbox = _SuiteSandbox(existing=set(), git_stdout="should-not-be-used.py\n")
    result = run_full_test_suite(sandbox)
    assert result.exit_code == 0
    assert result.ran_tests is True
    pytest_cmds = [c for c in sandbox.ran if "python -m pytest" in c]
    assert pytest_cmds == ["cd /home/user/repo && python -m pytest -q"]
    assert not any("git -C" in c for c in sandbox.ran)
    assert not any("API_KEY=" in c for c in sandbox.ran)


def test_relevant_python_test_files_maps_non_app_and_skips_fixtures():
    exists = {"tests/test_util.py"}
    mapped = relevant_python_test_files(
        [
            "backend/src/util.py",
            "backend/tests/fixtures/autopatch_phase34.py",
            "backend/conftest.py",
        ],
        test_file_exists=lambda rel: rel in exists,
    )
    assert mapped == ["tests/test_util.py"]


def test_full_suite_relevant_tests_nonzero_is_not_skipped():
    sandbox = _SuiteSandbox(
        existing={
            "/home/user/repo/backend",
            "/home/user/repo/backend/tests/test_harness.py",
        },
        git_stdout="backend/app/services/harness.py\n",
        pytest_exit=1,
        pytest_stderr="AssertionError: expected 2",
    )
    result = run_full_test_suite(sandbox)
    assert result.ran_tests is True
    assert result.skipped is False
    assert result.exit_code == 1
    assert extra_suite_ok(result) is False
    assert any("python -m pytest" in c for c in sandbox.ran)


def test_full_suite_fixture_only_patch_skips_additional_tests():
    sandbox = _SuiteSandbox(
        existing={"/home/user/repo/backend"},
        git_stdout="backend/tests/fixtures/autopatch_phase34.py\n",
    )
    result = run_full_test_suite(sandbox)
    assert result.skipped is True
    assert result.ran_tests is False
    assert extra_suite_ok(result) is True
    assert not any("python -m pytest" in c for c in sandbox.ran)


def test_extra_suite_merge_message_does_not_claim_tests_passed_when_skipped():
    skipped = ReproductionResult(
        exit_code=0,
        stdout=ADDITIONAL_TESTS_SKIPPED,
        stderr="",
        ran_tests=False,
    )
    ran = ReproductionResult(exit_code=0, stdout="1 passed", stderr="")
    skip_msg = extra_suite_merge_message("owner/repo", skipped)
    assert "no additional project tests were selected" in skip_msg
    assert "all tests passed" not in skip_msg.lower()
    assert extra_suite_merge_message("owner/repo", ran) == "owner/repo is green"
    assert extra_suite_ok(None) is False
