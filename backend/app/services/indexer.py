from pathlib import Path

from tree_sitter import Language, Parser, Query, QueryCursor

import tree_sitter_javascript as tsjs
import tree_sitter_python as tspython
import tree_sitter_typescript as tstypescript

_PARSERS: dict[str, Parser] = {
    ".py": Parser(Language(tspython.language())),
    ".js": Parser(Language(tsjs.language())),
    ".jsx": Parser(Language(tsjs.language())),
    ".ts": Parser(Language(tstypescript.language_typescript())),
    ".tsx": Parser(Language(tstypescript.language_tsx())),
}

_QUERIES = {
    ".py": """
        (function_definition name: (identifier) @name)
        (class_definition name: (identifier) @name)
    """,
    ".js": """
        (function_declaration name: (identifier) @name)
        (class_declaration name: (identifier) @name)
    """,
    ".jsx": """
        (function_declaration name: (identifier) @name)
        (class_declaration name: (identifier) @name)
    """,
    ".ts": """
        (function_declaration name: (identifier) @name)
        (class_declaration name: (type_identifier) @name)
        (class_declaration name: (identifier) @name)
    """,
    ".tsx": """
        (function_declaration name: (identifier) @name)
        (class_declaration name: (type_identifier) @name)
        (class_declaration name: (identifier) @name)
    """,
}


def _kind_for_node(node) -> str:
    t = node.type
    if "class" in t:
        return "class"
    return "function"


def index_source(path: str, source: str) -> list[tuple[str, str, int]]:
    ext = Path(path).suffix
    parser = _PARSERS.get(ext)
    query_src = _QUERIES.get(ext)
    if parser is None or query_src is None:
        return []
    tree = parser.parse(source.encode("utf-8"))
    language = parser.language
    if language is None:
        return []
    hits: list[tuple[str, str, int]] = []
    for node in _capture_nodes(language, query_src, tree.root_node):
        name = node.text.decode("utf-8") if node.text else ""
        if not name:
            continue
        parent = node.parent
        kind = _kind_for_node(parent) if parent is not None else "function"
        hits.append((name, kind, node.start_point[0] + 1))
    return hits


def _capture_nodes(language, query_src, root):
    query = Query(language, query_src)
    captures = QueryCursor(query).captures(root)

    nodes = []
    for group in captures.values():
        nodes.extend(group)

    return nodes


def index_files(files: dict[str, str]) -> list[dict]:
    rows: list[dict] = []
    for path, source in files.items():
        for name, kind, line in index_source(path, source):
            rows.append({"path": path, "name": name, "kind": kind, "start_line": line})
    return rows
