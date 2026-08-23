from pathlib import Path

from tree_sitter import Language, Parser

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


_TARGET_NODES = {
    ".py": {
        "function_definition": "function",
        "class_definition": "class",
    },
    ".js": {
        "function_declaration": "function",
        "class_declaration": "class",
    },
    ".jsx": {
        "function_declaration": "function",
        "class_declaration": "class",
    },
    ".ts": {
        "function_declaration": "function",
        "class_declaration": "class",
    },
    ".tsx": {
        "function_declaration": "function",
        "class_declaration": "class",
    },
}


def _node_name(node) -> str:
    name_node = node.child_by_field_name("name")

    if name_node is None:
        return ""

    if name_node.text is None:
        return ""

    return name_node.text.decode("utf-8")


def _walk_nodes(node):
    yield node

    for child in node.children:
        yield from _walk_nodes(child)


def index_source(path: str, source: str) -> list[tuple[str, str, int]]:
    ext = Path(path).suffix.lower()

    parser = _PARSERS.get(ext)
    targets = _TARGET_NODES.get(ext)

    if parser is None or targets is None:
        return []

    tree = parser.parse(source.encode("utf-8"))

    hits: list[tuple[str, str, int]] = []

    for node in _walk_nodes(tree.root_node):
        kind = targets.get(node.type)

        if kind is None:
            continue

        name = _node_name(node)

        if not name:
            continue

        hits.append(
            (
                name,
                kind,
                node.start_point[0] + 1,
            )
        )

    return hits


def index_files(files: dict[str, str]) -> list[dict]:
    rows: list[dict] = []

    for path, source in files.items():
        for name, kind, line in index_source(path, source):
            rows.append(
                {
                    "path": path,
                    "name": name,
                    "kind": kind,
                    "start_line": line,
                }
            )

    return rows