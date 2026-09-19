from pathlib import Path

from app.services.indexer import (
    index_source,
    inspect_class_init_parameters,
    inspect_function_parameters,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample.py"


def test_index_python_fixture():
    source = FIXTURE.read_text(encoding="utf-8")
    hits = index_source("sample.py", source)
    names = {name for name, _kind, _line in hits}
    assert "Sample" in names
    assert "ping" in names
    assert "helper" in names
    kinds = {name: kind for name, kind, _line in hits}
    assert kinds["Sample"] == "class"
    assert kinds["helper"] == "function"


def test_index_javascript_modern_functions():
    source = """
function normalFunction() {
    return true;
}

const arrowFunction = () => {
    return true;
};

class Example {
    classMethod() {
        return true;
    }
}

export function exportedFunction() {
    return true;
}
"""

    hits = index_source("sample.js", source)

    found = {(name, kind) for name, kind, _line in hits}

    assert ("normalFunction", "function") in found
    assert ("arrowFunction", "function") in found
    assert ("classMethod", "method") in found
    assert ("exportedFunction", "function") in found


def test_inspect_function_parameters_marks_keyword_only():
    source = """def divide(a, /, b, *args, c, d=1, **kwargs):
    return a
"""
    params = inspect_function_parameters("sample.py", source, "divide")
    by_name = {item.name: item for item in params}
    assert "args" not in by_name
    assert "kwargs" not in by_name
    assert by_name["a"].keyword_only is False
    assert by_name["b"].keyword_only is False
    assert by_name["c"].keyword_only is True
    assert by_name["d"].keyword_only is True
    assert by_name["d"].default_is_simple_literal is True


def test_inspect_class_init_parameters_is_class_scoped():
    source = """class Other:
    def __init__(self, user: User):
        self.user = user

class Math:
    def __init__(self, scale: int = 1):
        self.scale = scale

    def divide(self, x, y):
        return x / y
"""
    params = inspect_class_init_parameters("sample.py", source, "Math")
    names = [item.name for item in params]
    assert names == ["self", "scale"]
    assert params[1].default_source == "1"
    other = inspect_class_init_parameters("sample.py", source, "Other")
    assert [item.name for item in other] == ["self", "user"]
    assert inspect_class_init_parameters("sample.py", source, "Missing") == []