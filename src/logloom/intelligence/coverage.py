"""Intelligence pass to calculate function instrumentation coverage metrics."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Set, Optional
from ..graph.model import LogLoomGraph, CoverageMetrics

try:
    from tree_sitter import Language, Parser, Query
    try:
        from tree_sitter import QueryCursor
    except ImportError:
        QueryCursor = None
except ImportError:
    # tree-sitter might not be installed, handled gracefully
    Language = None
    Parser = None
    Query = None
    QueryCursor = None

logger = logging.getLogger(__name__)

_PYTHON_EXTS = {".py"}
_GO_EXTS = {".go"}
_TS_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


def compute_coverage(
    graph: LogLoomGraph,
    source_paths: List[Path],
    languages: List[str],
    defined_functions: Optional[Set[str]] = None,
) -> CoverageMetrics:
    """Scan all source files to count all functions and compute coverage."""
    if defined_functions is None:
        if Parser is None:
            return CoverageMetrics(
                total_functions=0,
                instrumented_functions=0,
                coverage_pct=0.0,
                uninstrumented=[],
            )

        all_files: List[Path] = []
        for path in source_paths:
            if path.is_file():
                all_files.append(path)
            elif path.is_dir():
                all_files.extend(path.rglob("*"))

        defined_functions = set()

        for f in all_files:
            suffix = f.suffix
            if suffix in _PYTHON_EXTS and "python" in languages:
                try:
                    defined_functions.update(_extract_python_functions(f))
                except Exception as e:
                    logger.debug(f"Failed to extract Python functions from {f}: {e}")

            elif suffix in _GO_EXTS and "go" in languages:
                # Skip test files as scanners exclude them
                if f.name.endswith("_test.go"):
                    continue
                try:
                    defined_functions.update(_extract_go_functions(f))
                except Exception as e:
                    logger.debug(f"Failed to extract Go functions from {f}: {e}")

            elif suffix in _TS_EXTS and "typescript" in languages:
                try:
                    defined_functions.update(_extract_ts_functions(f))
                except Exception as e:
                    logger.debug(f"Failed to extract TypeScript functions from {f}: {e}")

    # Build set of instrumented functions in the graph as f"{module}:{function}"
    instrumented_functions: Set[str] = set()
    for node in graph.nodes.values():
        if node.function and node.function != "<module>":
            instrumented_functions.add(f"{node.module}:{node.function}")

    # Calculate metrics
    # Note: Only consider functions defined in scanned modules.
    # We filter instrumented_functions to only those that are in defined_functions
    # in case some functions are dynamically generated or external.
    actual_instrumented = defined_functions & instrumented_functions
    
    total = len(defined_functions)
    instrumented_count = len(actual_instrumented)
    pct = (instrumented_count / max(total, 1)) * 100.0

    uninstrumented_list = sorted(list(defined_functions - actual_instrumented))

    return CoverageMetrics(
        total_functions=total,
        instrumented_functions=instrumented_count,
        coverage_pct=round(pct, 2),
        uninstrumented=uninstrumented_list,
    )


def _get_matches(query: Query, root_node) -> list:
    if QueryCursor is not None:
        cursor = QueryCursor(query)
        return cursor.matches(root_node)
    else:
        return query.matches(root_node)


def _extract_python_functions(file_path: Path) -> List[str]:
    import tree_sitter_python as tspython

    try:
        lang = Language(tspython.language())
    except TypeError:
        lang = Language(tspython.language(), "python")

    parser = Parser(lang)
    try:
        source = file_path.read_bytes()
    except (IOError, OSError):
        return []

    tree = parser.parse(source)
    query = Query(lang, "(function_definition name: (identifier) @name)")
    matches = _get_matches(query, tree.root_node)

    # Derive module path
    parts = list(file_path.with_suffix("").parts)
    if "src" in parts:
        idx = parts.index("src")
        module = ".".join(parts[idx + 1 :])
    else:
        module = ".".join(parts[-3:])

    funcs = []
    for match in matches:
        captures = match[1]
        for node in captures.get("name", []):
            func_name = node.text.decode("utf-8")
            funcs.append(f"{module}:{func_name}")
    return funcs


def _extract_go_functions(file_path: Path) -> List[str]:
    import tree_sitter_go as tsgo

    try:
        lang = Language(tsgo.language())
    except TypeError:
        lang = Language(tsgo.language(), "go")

    parser = Parser(lang)
    try:
        source = file_path.read_bytes()
    except (IOError, OSError):
        return []

    tree = parser.parse(source)
    query = Query(
        lang,
        """
    [
      (function_declaration name: (identifier) @name)
      (method_declaration name: (field_identifier) @name)
    ]
    """,
    )
    matches = _get_matches(query, tree.root_node)

    module = str(file_path.with_suffix(""))
    funcs = []

    for match in matches:
        captures = match[1]
        for node in captures.get("name", []):
            func_name = node.text.decode("utf-8")
            parent = node.parent
            receiver_type = None
            if parent and parent.type == "method_declaration":
                receiver = parent.child_by_field_name("receiver")
                if receiver:
                    for child in receiver.children:
                        if child.type == "parameter_declaration":
                            type_node = child.child_by_field_name("type")
                            if type_node:
                                receiver_type = (
                                    type_node.text.decode("utf-8").lstrip("*")
                                )
            if receiver_type:
                func_name = f"{receiver_type}.{func_name}"
            funcs.append(f"{module}:{func_name}")
    return funcs


def _extract_ts_functions(file_path: Path) -> List[str]:
    lang = None
    try:
        import tree_sitter_typescript as ts_typescript
        try:
            lang = Language(ts_typescript.language_typescript())
        except TypeError:
            lang = Language(ts_typescript.language_typescript(), "typescript")
    except ImportError:
        try:
            import tree_sitter_javascript as ts_javascript
            try:
                lang = Language(ts_javascript.language())
            except TypeError:
                lang = Language(ts_javascript.language(), "javascript")
        except ImportError:
            return []

    if not lang:
        return []

    parser = Parser(lang)
    try:
        source = file_path.read_bytes()
    except (IOError, OSError):
        return []

    tree = parser.parse(source)
    query = Query(
        lang,
        """
    [
      (function_declaration name: (identifier) @name)
      (method_definition name: (property_identifier) @name)
      (method_definition name: (private_property_identifier) @name)
      (variable_declarator name: (identifier) @name value: [(arrow_function) (function_expression)])
    ]
    """,
    )
    matches = _get_matches(query, tree.root_node)

    module = str(file_path.with_suffix(""))
    funcs = []

    for match in matches:
        captures = match[1]
        for node in captures.get("name", []):
            func_name = node.text.decode("utf-8")
            parent = node.parent
            class_name = None
            while parent:
                if parent.type in ("class_declaration", "class"):
                    name_node = parent.child_by_field_name("name")
                    if name_node:
                        class_name = name_node.text.decode("utf-8")
                    break
                parent = parent.parent

            if class_name:
                func_name = f"{class_name}.{func_name}"
            funcs.append(f"{module}:{func_name}")
    return funcs
