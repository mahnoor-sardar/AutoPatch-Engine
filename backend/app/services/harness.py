from dataclasses import dataclass

from e2b import Sandbox

REPRO_TIMEOUT = 120


@dataclass(frozen=True)
class ReproductionResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def reproduced(self) -> bool:
        return self.exit_code != 0


def run_reproduction_test(
    sandbox: Sandbox,
    test_path: str,
    test_source: str,
) -> ReproductionResult:
    try:
        sandbox.files.write(
            f"/home/user/repo/{test_path}",
            test_source,
        )

        install = sandbox.commands.run(
            "cd /home/user/repo/backend && "
            "python -m pip install -r requirements.txt",
            timeout=REPRO_TIMEOUT,
        )

        result = sandbox.commands.run(
            f"cd /home/user/repo && "
            f"python -m pytest {test_path} -q",
            timeout=REPRO_TIMEOUT,
        )

        return ReproductionResult(
            exit_code=0,
            stdout=(
                (install.stdout or "")
                + (result.stdout or "")
            ),
            stderr=result.stderr or "",
        )

    except Exception as exc:
        exit_code = getattr(exc, "exit_code", 1)

        stdout = getattr(exc, "stdout", "") or ""
        stderr = getattr(exc, "stderr", "") or ""

        if not stderr:
            stderr = str(exc)

        return ReproductionResult(
            exit_code=int(exit_code),
            stdout=stdout,
            stderr=stderr,
        )