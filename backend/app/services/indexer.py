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


_COMMON_JS_TARGETS = {
    "function_declaration": "function",
    "class_declaration": "class",
    "method_definition": "method",
    "arrow_function": "function",
}


_TARGET_NODES = {
    ".py": {
        "function_definition": "function",
        "class_definition": "class",
    },
    ".js": _COMMON_JS_TARGETS,
    ".jsx": _COMMON_JS_TARGETS,
    ".ts": _COMMON_JS_TARGETS,
    ".tsx": _COMMON_JS_TARGETS,
}


def _node_name(node) -> str:
    name_node = node.child_by_field_name("name")

    if name_node is not None and name_node.text is not None:
        return name_node.text.decode("utf-8")

    # Arrow functions don't have a "name" field.
    # Look at the parent variable declarator:
    # const foo = () => {}
    parent = node.parent

    if parent is not None and parent.type == "variable_declarator":
        name_node = parent.child_by_field_name("name")

        if name_node is not None and name_node.text is not None:
            return name_node.text.decode("utf-8")

    # Exported function expressions can also be wrapped
    # inside an export/default expression.
    if parent is not None:
        name_node = parent.child_by_field_name("name")

        if name_node is not None and name_node.text is not None:
            return name_node.text.decode("utf-8")

    return ""


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


def function_parameters(path: str, source: str, name: str) -> list[str]:
    ext = Path(path).suffix.lower()
    parser = _PARSERS.get(ext)
    if parser is None:
        return []

    tree = parser.parse(source.encode("utf-8"))
    for node in _walk_nodes(tree.root_node):
        if _node_name(node) != name:
            continue
        params = node.child_by_field_name("parameters")
        if params is None:
            params = node.child_by_field_name("formal_parameters")
        if params is None:
            continue
        names: list[str] = []
        for child in params.children:
            if child.type in {"identifier", "required_parameter"}:
                text = child.text.decode("utf-8") if child.text else ""
                if text and text not in {"self", "cls", "(", ")", ",", "*"}:
                    if text.startswith("*"):
                        continue
                    names.append(text.split(":")[0].strip())
            if child.type == "typed_parameter" and child.child_by_field_name(
                "name"
            ):
                names.append(
                    child.child_by_field_name("name").text.decode("utf-8")
                )
        return [n for n in names if n and n not in {"self", "cls"}]
    return []


def index_files(
    files: dict[str, str],
) -> list[tuple[str, str, str, int]]:
    rows: list[tuple[str, str, str, int]] = []

    for path, source in files.items():
        for name, kind, line in index_source(path, source):
            rows.append(
                (
                    path,
                    name,
                    kind,
                    line,
                )
            )

    return rows