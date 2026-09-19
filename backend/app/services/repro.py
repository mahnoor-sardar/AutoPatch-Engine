from dataclasses import dataclass
from pathlib import Path
import re

from app.services.diagnostic import DiagnosticLocation
from app.services.indexer import (
    ParameterInfo,
    enclosing_class_name,
    function_parameters,
    inspect_class_init_parameters,
    inspect_function_parameters,
)


_JS_ERROR_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_GENERIC_JS_ERRORS = frozenset({"Error", "Exception"})
_JS_BUILTIN_ERRORS = frozenset(
    {
        "TypeError",
        "RangeError",
        "SyntaxError",
        "ReferenceError",
        "URIError",
        "EvalError",
        "AggregateError",
    }
)


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


_IMPLICIT_PYTHON_PARAMS = frozenset({"self", "cls"})


def _dummy_for_exception(exception_type: str | None, message: str | None) -> str:
    """Deterministic dummy that tends to reproduce, not hide, the diagnosed error."""
    kind = (exception_type or "").split(".")[-1]
    text = f"{kind} {message or ''}".lower()
    if kind == "ZeroDivisionError" or "division by zero" in text:
        return "0"
    return "None"


def _normalize_annotation(raw: str | None) -> str | None:
    if not raw:
        return None
    text = raw.strip()
    if len(text) >= 2 and text[0] in {'"', "'"} and text[-1] == text[0]:
        text = text[1:-1].strip()
    return text or None


def _python_arg_for_param(
    param: ParameterInfo,
    *,
    exception_type: str | None,
    message: str | None,
) -> str | None:
    if param.name in _IMPLICIT_PYTHON_PARAMS:
        return None
    if param.default_is_simple_literal and param.default_source:
        return param.default_source
    annotation = _normalize_annotation(param.annotation)
    if annotation in _PRIMITIVE_ARGS:
        return _PRIMITIVE_ARGS[annotation]
    if annotation:
        compact = annotation.replace(" ", "")
        for prim, dummy in _PRIMITIVE_ARGS.items():
            if compact in {
                prim,
                f"Optional[{prim}]",
                f"{prim}|None",
                f"None|{prim}",
            }:
                return dummy
        return None
    return _dummy_for_exception(exception_type, message)


def _python_call_args(
    params: list[ParameterInfo],
    exception_type: str | None,
    message: str | None,
) -> str:
    if not params:
        return ""
    args: list[str] = []
    missing: list[str] = []
    for param in params:
        if param.name in _IMPLICIT_PYTHON_PARAMS:
            continue
        value = _python_arg_for_param(
            param, exception_type=exception_type, message=message
        )
        if value is None:
            missing.append(param.name)
        elif param.keyword_only:
            args.append(f"{param.name}={value}")
        else:
            args.append(value)
    if missing:
        names = ", ".join(missing)
        raise ValueError(
            "reproduction synthesis incomplete: "
            f"unsupported required parameter(s): {names}"
        )
    return ", ".join(args)


def _python_instance_construction(
    path: str,
    source: str,
    owner: str,
    exception_type: str | None,
    message: str | None,
) -> str:
    init_params = inspect_class_init_parameters(path, source, owner)
    init_args = _python_call_args(init_params, exception_type, message)
    if init_args:
        return f"{owner}({init_args})"
    return f"{owner}()"


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
    call_args = _python_call_args(params, exception_type, message)
    owner = enclosing_class_name(location.path, source, location.name)
    has_self = any(param.name == "self" for param in params)

    module_path = (
        Path(location.path).with_suffix("").as_posix().replace("/", ".")
    )
    imported = owner or location.name
    if owner and has_self:
        constructed = _python_instance_construction(
            location.path, source, owner, exception_type, message
        )
        invoked = (
            f"{constructed}.{location.name}({call_args})"
            if call_args
            else f"{constructed}.{location.name}()"
        )
    elif owner:
        invoked = f"{owner}.{location.name}({call_args})"
    else:
        invoked = f"{location.name}({call_args})"

    test_source = f'''import asyncio
import inspect
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_reproduces_{location.name}_failure():
    from {module_path} import {imported}

    expected_exception = {expected_exception}

    try:
        _result = {invoked}
        if inspect.isawaitable(_result):
            asyncio.run(_result)
    except expected_exception:
        raise
'''

    return ReproductionTest(
        test_path="tests/autopatch_repro_test.py",
        test_source=test_source,
    )


def _javascript_expected_error(exception_type: str | None) -> str | None:
    if not exception_type:
        return None
    name = exception_type.strip()
    if not _JS_ERROR_IDENTIFIER.fullmatch(name):
        return None
    if name in _GENERIC_JS_ERRORS:
        return None
    if not (name.endswith("Error") or name.endswith("Exception")):
        return None
    return name


def _javascript_expected_error_expr(name: str) -> str:
    if name in _JS_BUILTIN_ERRORS:
        return name
    return f"globalThis.{name}"


def _javascript_call_args(
    params: list[str],
    exception_type: str | None,
    message: str | None,
) -> str:
    """JS missing arguments are represented as undefined (the diagnosed case)."""
    if not params:
        return ""
    return ", ".join("undefined" for _ in params)


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
    args = _javascript_call_args(params, exception_type, message)
    rel = location.path.replace("\\", "/")
    suffix = Path(location.path).suffix.lower()
    is_typescript = suffix in {".ts", ".tsx"}
    test_path = (
        "tests/autopatch_repro.test.ts"
        if is_typescript
        else "tests/autopatch_repro.test.mjs"
    )

    expected_error = _javascript_expected_error(exception_type)
    expected_line = (
        f"const expected_exception = {_javascript_expected_error_expr(expected_error)};\n\n"
        if expected_error
        else ""
    )

    test_source = f'''import test from "node:test";

{expected_line}test("reproduces {location.name} failure", async () => {{
  const mod = await import("../{rel}");
  const target = mod.{location.name} ?? mod.default ?? mod;
  const fn = typeof target === "function" ? target : target.{location.name};
  await Promise.resolve(fn({args}));
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
