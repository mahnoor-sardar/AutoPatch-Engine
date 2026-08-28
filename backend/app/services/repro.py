from dataclasses import dataclass
from pathlib import Path

from app.services.diagnostic import DiagnosticLocation
from app.services.indexer import ParameterInfo, function_parameters, inspect_function_parameters


_PRIMITIVE_ARGS = {
    "int": "0",
    "float": "0.0",
    "str": '""',
    "bool": "False",
}


@dataclass(frozen=True)
class ReproductionTest:
    test_path: str
    test_source: str


def _normalize_annotation(raw: str | None) -> str | None:
    if not raw:
        return None
    text = raw.strip()
    if len(text) >= 2 and text[0] in {'"', "'"} and text[-1] == text[0]:
        text = text[1:-1].strip()
    return text or None


def _python_arg_for_param(param: ParameterInfo) -> str | None:
    if param.default_is_simple_literal and param.default_source:
        return param.default_source
    annotation = _normalize_annotation(param.annotation)
    if annotation in _PRIMITIVE_ARGS:
        return _PRIMITIVE_ARGS[annotation]
    return None


def _python_call_args(params: list[ParameterInfo]) -> str:
    if not params:
        return ""
    args: list[str] = []
    missing: list[str] = []
    for param in params:
        value = _python_arg_for_param(param)
        if value is None:
            missing.append(param.name)
        else:
            args.append(value)
    if missing:
        names = ", ".join(missing)
        raise ValueError(
            "reproduction synthesis incomplete: "
            f"unsupported required parameter(s): {names}"
        )
    return ", ".join(args)


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
    params = inspect_function_parameters(location.path, source, location.name)
    call_args = _python_call_args(params)

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
    except Exception:
        return
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
