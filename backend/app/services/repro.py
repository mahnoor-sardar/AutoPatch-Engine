from dataclasses import dataclass
from pathlib import Path

from app.services.diagnostic import DiagnosticLocation


@dataclass(frozen=True)
class ReproductionTest:
    test_path: str
    test_source: str


def synthesize_python_repro(
    location: DiagnosticLocation,
    source: str,
    exception_type: str | None,
    message: str | None,
) -> ReproductionTest:
    if Path(location.path).suffix.lower() != ".py":
        raise ValueError(
            "Python reproduction synthesis requires a Python source file"
        )

    if not location.name:
        raise ValueError(
            "Diagnostic location must contain a symbol name"
        )

    expected_exception = exception_type or "Exception"

    module_path = (
        Path(location.path)
        .with_suffix("")
        .as_posix()
        .replace("/", ".")
    )

    test_source = f'''import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_reproduces_{location.name}_failure():
    from {module_path} import {location.name}

    expected_exception = {expected_exception}

    try:
        {location.name}()
    except expected_exception:
        raise
'''

    return ReproductionTest(
        test_path="tests/autopatch_repro_test.py",
        test_source=test_source,
    )