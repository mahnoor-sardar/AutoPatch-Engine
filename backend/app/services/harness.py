from dataclasses import dataclass
from pathlib import Path
import re
import shlex

from app.services.e2b_runner import COMMAND_TIMEOUT, install_project_dependencies, run_sandbox_command

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
    ran_tests: bool = True

    @property
    def skipped(self) -> bool:
        return not self.ran_tests

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

    @property
    def passed_clean(self) -> bool:
        """True when the repro test passed with no setup/synthesis failure."""
        if self.setup_failed or self.synthesis_failed:
            return False
        return self.exit_code == 0


def _expected_exception_from_source(test_source: str) -> str | None:
    match = _EXPECTED_EXCEPTION_ASSIGN.search(test_source)
    if match is None:
        return None
    name = match.group(1).split(".")[-1]
    if name in {"Exception", "BaseException", "Error"}:
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
    return run_sandbox_command(sandbox, command, timeout)


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
            exit_code=int(getattr(result, "exit_code", 0) or 0),
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


_BACKEND_PYTEST_ENV = (
    "API_KEY=dev-local-key GITHUB_WEBHOOK_SECRET=dev-webhook-secret"
)
_TEST_BASENAME = re.compile(r"^(test_.+\.py|.+_test\.py)$")
ADDITIONAL_TESTS_SKIPPED = (
    "No additional project tests were selected; synthesized reproduction passed."
)


def _normalize_git_path(path: str) -> str:
    return path.strip().replace("\\", "/").lstrip("./")


def extra_suite_ok(result: ReproductionResult | None) -> bool:
    if result is None:
        return False
    if not result.ran_tests:
        return True
    return result.exit_code == 0


def extra_suite_merge_message(repo: str, result: ReproductionResult | None) -> str:
    if result is not None and not result.ran_tests:
        return (
            f"{repo}: no additional project tests were selected; "
            "synthesized reproduction passed"
        )
    return f"{repo} is green"


def _rel_under_root(path: str, root: str) -> str | None:
    path = _normalize_git_path(path)
    prefix = root.rstrip("/") + "/"
    if path.startswith(prefix):
        return path[len(prefix) :]
    return None


def relevant_python_test_files(
    changed_paths: list[str],
    *,
    test_file_exists,
    root_prefix: str = "backend",
) -> list[str]:
    """Pytest paths relative to the package root (e.g. /home/user/repo/backend)."""
    relevant: list[str] = []
    seen: set[str] = set()

    def _add(rel: str) -> None:
        rel = rel.replace("\\", "/")
        if rel not in seen:
            seen.add(rel)
            relevant.append(rel)

    for raw in changed_paths:
        if not _normalize_git_path(raw).endswith(".py"):
            continue
        rel = _rel_under_root(raw, root_prefix)
        if rel is None:
            continue
        parts = Path(rel).parts
        if "fixtures" in parts:
            continue
        name = Path(rel).name
        if name == "conftest.py":
            continue
        if _TEST_BASENAME.match(name):
            _add(rel)
            continue
        if name == "__init__.py":
            continue
        stem = Path(rel).stem
        parent = Path(rel).parent.as_posix()
        candidates = [f"tests/test_{stem}.py"]
        if parent != ".":
            candidates.extend(
                [
                    f"{parent}/test_{stem}.py",
                    f"{parent}/{stem}_test.py",
                    f"tests/{parent}/test_{stem}.py",
                ]
            )
        else:
            candidates.append(f"{stem}_test.py")
        for candidate in candidates:
            if test_file_exists(candidate):
                _add(candidate)
    return relevant


def relevant_backend_test_files(
    changed_paths: list[str],
    *,
    test_file_exists,
) -> list[str]:
    return relevant_python_test_files(
        changed_paths,
        test_file_exists=test_file_exists,
        root_prefix="backend",
    )


def _changed_python_files(sandbox) -> list[str]:
    result = _run_command(
        sandbox,
        "git -C /home/user/repo diff --name-only -- '*.py'",
        REPRO_TIMEOUT,
    )
    return [
        line.strip()
        for line in (result.stdout or "").splitlines()
        if line.strip()
    ]


def run_full_test_suite(sandbox) -> ReproductionResult:
    try:
        if test_path_exists(sandbox, "/home/user/repo/package.json"):
            result = _run_command(
                sandbox,
                "cd /home/user/repo && npm test --if-present",
                REPRO_TIMEOUT,
            )
        elif test_path_exists(sandbox, "/home/user/repo/backend"):
            changed = _changed_python_files(sandbox)
            relevant = relevant_python_test_files(
                changed,
                test_file_exists=lambda rel: test_path_exists(
                    sandbox, f"/home/user/repo/backend/{rel}"
                ),
            )
            if not relevant:
                return ReproductionResult(
                    exit_code=0,
                    stdout=ADDITIONAL_TESTS_SKIPPED,
                    stderr="",
                    ran_tests=False,
                )
            quoted = " ".join(shlex.quote(p) for p in relevant)
            result = _run_command(
                sandbox,
                "cd /home/user/repo/backend && "
                f"{_BACKEND_PYTEST_ENV} python -m pytest -q {quoted}",
                REPRO_TIMEOUT,
            )
        else:
            result = _run_command(
                sandbox,
                "cd /home/user/repo && python -m pytest -q",
                REPRO_TIMEOUT,
            )
        return ReproductionResult(
            exit_code=int(getattr(result, "exit_code", 0) or 0),
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            ran_tests=True,
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
