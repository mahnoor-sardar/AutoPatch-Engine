from dataclasses import dataclass
from pathlib import Path
import re

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


@dataclass(frozen=True)
class ParameterInfo:
    name: str
    annotation: str | None = None
    default_source: str | None = None
    default_is_simple_literal: bool = False


_SAFE_DEFAULT_SOURCE = re.compile(
    r"""^(?:
        None|True|False|
        -?\d+(?:\.\d+)?|
        (?:[rRuUfFbB]*)(['\"])(?:\\.|(?!\1).)*\1
    )$""",
    re.VERBOSE,
)

_SKIP_PARAM_TYPES = {
    "(",
    ")",
    ",",
    "comment",
    "list_splat_pattern",
    "dictionary_splat_pattern",
    "keyword_separator",
    "positional_separator",
    "tuple_pattern",
}


def _decode_node(node) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8")


def _is_safe_default_source(text: str) -> bool:
    return bool(_SAFE_DEFAULT_SOURCE.fullmatch(text.strip()))


def _first_child_of_type(node, type_name: str):
    for child in node.children:
        if child.type == type_name:
            return child
    return None


def _python_parameter_info(child) -> ParameterInfo | None:
    if child.type in _SKIP_PARAM_TYPES:
        return None
    if child.type not in {
        "identifier",
        "typed_parameter",
        "default_parameter",
        "typed_default_parameter",
    }:
        return None

    name_node = child if child.type == "identifier" else child.child_by_field_name("name")
    if name_node is None:
        name_node = _first_child_of_type(child, "identifier")
    if name_node is not None and name_node.type in {
        "list_splat_pattern",
        "dictionary_splat_pattern",
    }:
        return None

    name = _decode_node(name_node)
    if not name or name.startswith("*"):
        return None

    type_node = child.child_by_field_name("type")
    if type_node is None:
        type_node = _first_child_of_type(child, "type")
    annotation = _decode_node(type_node).strip() or None

    value_node = child.child_by_field_name("value")
    if value_node is None and child.type in {
        "default_parameter",
        "typed_default_parameter",
    }:
        for grandchild in reversed(child.children):
            if grandchild.type not in {"=", ":", "type", "identifier"}:
                value_node = grandchild
                break
    default_source = _decode_node(value_node).strip() or None
    default_is_simple = bool(
        default_source and _is_safe_default_source(default_source)
    )
    return ParameterInfo(
        name=name,
        annotation=annotation,
        default_source=default_source,
        default_is_simple_literal=default_is_simple,
    )


def inspect_function_parameters(
    path: str, source: str, name: str
) -> list[ParameterInfo]:
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
        infos: list[ParameterInfo] = []
        for child in params.children:
            if ext == ".py":
                info = _python_parameter_info(child)
            else:
                info = _js_parameter_info(child)
            if info is not None:
                infos.append(info)
        return infos
    return []


def enclosing_class_name(path: str, source: str, function_name: str) -> str | None:
    """Return the nearest class that owns ``function_name``, if any."""
    if Path(path).suffix.lower() != ".py":
        return None
    parser = _PARSERS.get(".py")
    if parser is None:
        return None
    tree = parser.parse(source.encode("utf-8"))
    for node in _walk_nodes(tree.root_node):
        if node.type != "function_definition":
            continue
        if _node_name(node) != function_name:
            continue
        parent = node.parent
        while parent is not None:
            if parent.type == "class_definition":
                owner = _node_name(parent)
                return owner or None
            parent = parent.parent
        return None
    return None


def _js_parameter_info(child) -> ParameterInfo | None:
    if child.type in {"identifier", "required_parameter"}:
        text = _decode_node(child)
        if text and text not in {"self", "cls", "(", ")", ",", "*"}:
            if text.startswith("*"):
                return None
            return ParameterInfo(name=text.split(":")[0].strip())
    if child.type == "typed_parameter" and child.child_by_field_name("name"):
        name = _decode_node(child.child_by_field_name("name"))
        if name and name not in {"self", "cls"}:
            return ParameterInfo(name=name)
    return None


def function_parameters(path: str, source: str, name: str) -> list[str]:
    return [item.name for item in inspect_function_parameters(path, source, name)]


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