from pathlib import Path

from app.services.indexer import index_source

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