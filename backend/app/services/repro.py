from dataclasses import dataclass
from pathlib import Path

from app.services.diagnostic import DiagnosticLocation
from app.services.indexer import function_parameters


@dataclass(frozen=True)
class ReproductionTest:
    test_path: str
    test_source: str


def _dummy_python_args(params: list[str]) -> str:
    if not params:
        return ""
    return ", ".join("None" for _ in params)


def synthesize_python_repro(
    location: DiagnosticLocation,
    source: str,
    exception_type: str | None,
    message: str | None,
) -> ReproductionTest:
    suffix = Path(location.path).suffix.lower()
    if suffix != ".py":
        raise ValueError(
            "Python reproduction synthesis requires a Python source file"
        )

    if not location.name:
        raise ValueError("Diagnostic location must contain a symbol name")

    expected_exception = exception_type or "Exception"
    params = function_parameters(location.path, source, location.name)
    call_args = _dummy_python_args(params)

    module_path = (
        Path(location.path).with_suffix("").as_posix().replace("/", ".")
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
        {location.name}({call_args})
    except expected_exception:
        raise
'''

    return ReproductionTest(
        test_path="tests/autopatch_repro_test.py",
        test_source=test_source,
    )


def synthesize_javascript_repro(
    location: DiagnosticLocation,
    source: str,
    exception_type: str | None,
    message: str | None,
) -> ReproductionTest:
    suffix = Path(location.path).suffix.lower()
    if suffix not in {".js", ".jsx", ".ts", ".tsx", ".mjs"}:
        raise ValueError(
            "JavaScript reproduction synthesis requires a JS/TS source file"
        )

    if not location.name:
        raise ValueError("Diagnostic location must contain a symbol name")

    params = function_parameters(location.path, source, location.name)
    args = ", ".join("undefined" for _ in params)
    rel = location.path.replace("\\", "/")
    suffix = Path(location.path).suffix.lower()
    is_typescript = suffix in {".ts", ".tsx"}
    test_path = (
        "tests/autopatch_repro.test.ts"
        if is_typescript
        else "tests/autopatch_repro.test.mjs"
    )

    test_source = f'''import test from "node:test";
import assert from "node:assert/strict";

test("reproduces {location.name} failure", async () => {{
  const mod = await import("../{rel}");
  const target = mod.{location.name} ?? mod.default ?? mod;
  const fn = typeof target === "function" ? target : target.{location.name};
  assert.throws(() => fn({args}));
}});
'''

    return ReproductionTest(
        test_path=test_path,
        test_source=test_source,
    )


def synthesize_repro(
    location: DiagnosticLocation,
    source: str,
    exception_type: str | None,
    message: str | None,
) -> ReproductionTest:
    suffix = Path(location.path).suffix.lower()
    if suffix == ".py":
        return synthesize_python_repro(
            location, source, exception_type, message
        )
    if suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs"}:
        return synthesize_javascript_repro(
            location, source, exception_type, message
        )
    raise ValueError("Unsupported source language for reproduction synthesis")
