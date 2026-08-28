from dataclasses import dataclass
import re

from app.services.e2b_runner import COMMAND_TIMEOUT, install_project_dependencies

REPRO_TIMEOUT = COMMAND_TIMEOUT

_SYNTHESIS_MARKERS = (
    "missing",
    "required positional argument",
    "required argument",
    "TypeError: ",
)


_EXPECTED_EXCEPTION_ASSIGN = re.compile(
    r"expected_exception\s*=\s*([A-Za-z_][\w.]*)"
)


@dataclass(frozen=True)
class ReproductionResult:
    exit_code: int
    stdout: str
    stderr: str
    setup_failed: bool = False
    synthesis_failed: bool = False
    expected_exception: str | None = None

    @property
    def reproduced(self) -> bool:
        if self.setup_failed or self.synthesis_failed:
            return False
        if self.exit_code == 0:
            return False
        if not _stderr_matches_expected(
            self.stdout, self.stderr, self.expected_exception
        ):
            return False
        return True


def _expected_exception_from_source(test_source: str) -> str | None:
    match = _EXPECTED_EXCEPTION_ASSIGN.search(test_source)
    if match is None:
        return None
    name = match.group(1).split(".")[-1]
    if name in {"Exception", "BaseException"}:
        return None
    return name


def _stderr_matches_expected(
    stdout: str, stderr: str, expected_exception: str | None
) -> bool:
    if not expected_exception:
        return True
    combined = f"{stdout}\n{stderr}"
    return expected_exception in combined


def _is_synthesis_failure(stderr: str) -> bool:
    text = stderr.lower()
    return "required positional argument" in text or (
        "typeerror" in text and "missing" in text and "argument" in text
    )


def _write_file(sandbox, path: str, content: str) -> None:
    if hasattr(sandbox, "write_file"):
        sandbox.write_file(path, content)
        return
    sandbox.files.write(path, content)


def _run_command(sandbox, command: str, timeout: int):
    if hasattr(sandbox, "commands"):
        return sandbox.commands.run(command, timeout=timeout)
    return sandbox.run(command, timeout=timeout)


def run_reproduction_test(
    sandbox,
    test_path: str,
    test_source: str,
    *,
    install_dependencies: bool = True,
) -> ReproductionResult:
    _write_file(
        sandbox,
        f"/home/user/repo/{test_path}",
        test_source,
    )

    install_out = ""
    if install_dependencies:
        install_code, install_out, install_err = install_project_dependencies(
            sandbox
        )
        if install_code != 0:
            return ReproductionResult(
                exit_code=install_code,
                stdout=install_out,
                stderr=install_err,
                setup_failed=True,
            )

    try:
        result = _run_command(
            sandbox, _repro_command(test_path), REPRO_TIMEOUT
        )
        return ReproductionResult(
            exit_code=0,
            stdout=(install_out + (result.stdout or "")),
            stderr=result.stderr or "",
            expected_exception=_expected_exception_from_source(test_source),
        )
    except Exception as exc:
        exit_code = int(getattr(exc, "exit_code", 1) or 1)
        stdout = getattr(exc, "stdout", "") or ""
        stderr = getattr(exc, "stderr", "") or str(exc)
        synthesis_failed = _is_synthesis_failure(stderr)
        return ReproductionResult(
            exit_code=exit_code,
            stdout=install_out + stdout,
            stderr=stderr,
            synthesis_failed=synthesis_failed,
            expected_exception=_expected_exception_from_source(test_source),
        )


def _repro_command(test_path: str) -> str:
    if test_path.endswith(".py"):
        return f"cd /home/user/repo && python -m pytest {test_path} -q"
    if test_path.endswith((".ts", ".tsx", ".mts")):
        return (
            "cd /home/user/repo && "
            f"npx --yes tsx --test {test_path}"
        )
    return f"cd /home/user/repo && node --test {test_path}"


def run_full_test_suite(sandbox) -> ReproductionResult:
    try:
        if test_path_exists(sandbox, "/home/user/repo/package.json"):
            result = _run_command(
                sandbox,
                "cd /home/user/repo && npm test --if-present",
                REPRO_TIMEOUT,
            )
        else:
            result = _run_command(
                sandbox,
                "cd /home/user/repo && python -m pytest -q",
                REPRO_TIMEOUT,
            )
        return ReproductionResult(
            exit_code=getattr(result, "exit_code", 0) or 0,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )
    except Exception as exc:
        return ReproductionResult(
            exit_code=int(getattr(exc, "exit_code", 1) or 1),
            stdout=getattr(exc, "stdout", "") or "",
            stderr=getattr(exc, "stderr", "") or str(exc),
        )


def test_path_exists(sandbox, path: str) -> bool:
    result = _run_command(
        sandbox,
        f"test -e {path}; echo $?",
        30,
    )
    return (result.stdout or "").strip().endswith("0")
