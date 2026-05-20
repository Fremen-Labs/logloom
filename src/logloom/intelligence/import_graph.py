"""Extract module-level import relationships to build the codebase dependency graph."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

try:
    from tree_sitter import Language, Parser
except ImportError:
    Language = None
    Parser = None

logger = logging.getLogger(__name__)

_PYTHON_EXTS = {".py"}
_GO_EXTS = {".go"}
_TS_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


def compute_imports(source_paths: List[Path], languages: List[str], include_external: bool = False) -> Dict[str, List[str]]:
    """Compute module-to-imports mapping for all scanned files."""
    if Parser is None:
        return {}

    all_files: List[Path] = []
    for path in source_paths:
        if path.is_file():
            all_files.append(path)
        elif path.is_dir():
            all_files.extend(path.rglob("*"))

    imports_graph: Dict[str, List[str]] = {}

    for f in all_files:
        suffix = f.suffix
        if suffix in _PYTHON_EXTS and "python" in languages:
            try:
                mod_name = _get_py_module_path(f)
                imports_graph[mod_name] = _extract_python_imports(f)
            except Exception as e:
                logger.debug(f"Failed to extract Python imports from {f}: {e}")

        elif suffix in _GO_EXTS and "go" in languages:
            if f.name.endswith("_test.go"):
                continue
            try:
                mod_name = _get_go_module_path(f)
                imports_graph[mod_name] = _extract_go_imports(f)
            except Exception as e:
                logger.debug(f"Failed to extract Go imports from {f}: {e}")

        elif suffix in _TS_EXTS and "typescript" in languages:
            try:
                mod_name = _get_ts_module_path(f)
                imports_graph[mod_name] = _extract_ts_imports(f)
            except Exception as e:
                logger.debug(f"Failed to extract TypeScript imports from {f}: {e}")

    if not include_external:
        imports_graph = _filter_internal_imports(imports_graph)

    return imports_graph


def _filter_internal_imports(imports_graph: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Filter imports to only include modules that are internal to the scanned project."""
    internal_mods = set(imports_graph.keys())
    filtered_graph = {}

    for mod, imps in imports_graph.items():
        filtered_imps = []
        for imp in imps:
            # 1. Resolve relative import
            resolved_imp = imp
            if imp.startswith("."):
                dots = 0
                while dots < len(imp) and imp[dots] == ".":
                    dots += 1
                parent_parts = mod.split(".")
                if len(parent_parts) >= dots:
                    resolved_imp = ".".join(parent_parts[:-dots])
                    if imp[dots:]:
                        resolved_imp = f"{resolved_imp}.{imp[dots:]}"
                else:
                    resolved_imp = imp.lstrip(".")

            # 2. Check if the resolved import is one of our internal modules
            is_internal = False
            if resolved_imp in internal_mods:
                is_internal = True
            else:
                for internal_mod in internal_mods:
                    # Match end of path/module suffix (e.g., pkg/auth vs github.com/user/repo/pkg/auth)
                    if (
                        resolved_imp == internal_mod or
                        internal_mod.endswith("/" + resolved_imp) or
                        internal_mod.endswith("." + resolved_imp) or
                        resolved_imp.endswith("/" + internal_mod) or
                        resolved_imp.endswith("." + internal_mod)
                    ):
                        resolved_imp = internal_mod
                        is_internal = True
                        break

            if is_internal and resolved_imp != mod:
                filtered_imps.append(resolved_imp)

        filtered_graph[mod] = sorted(list(set(filtered_imps)))

    return filtered_graph


def _get_py_module_path(file_path: Path) -> str:
    parts = list(file_path.with_suffix("").parts)
    if "src" in parts:
        idx = parts.index("src")
        return ".".join(parts[idx+1:])
    return ".".join(parts[-3:])


def _get_go_module_path(file_path: Path) -> str:
    return str(file_path.with_suffix(""))


def _get_ts_module_path(file_path: Path) -> str:
    parts = list(file_path.with_suffix("").parts)
    for marker in ("src", "lib", "app", "pages", "components", "api"):
        if marker in parts:
            idx = parts.index(marker)
            return "/".join(parts[idx:])
    return "/".join(parts[-3:])


def _extract_python_imports(file_path: Path) -> List[str]:
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
    imports = []

    def walk(node):
        if node.type == "import_statement":
            for child in node.children:
                if child.type == "dotted_name":
                    imports.append(child.text.decode("utf-8"))
                elif child.type == "aliased_import":
                    dot_name = child.child_by_field_name("name")
                    if dot_name:
                        imports.append(dot_name.text.decode("utf-8"))
        elif node.type == "import_from_statement":
            module_name = node.child_by_field_name("module_name")
            if module_name:
                imports.append(module_name.text.decode("utf-8"))
        else:
            for child in node.children:
                walk(child)

    walk(tree.root_node)
    return sorted(list(set(imports)))


def _extract_go_imports(file_path: Path) -> List[str]:
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
    imports = []

    def walk(node):
        if node.type == "import_spec":
            for child in node.children:
                if child.type in ("interpreted_string_literal", "raw_string_literal"):
                    imports.append(child.text.decode("utf-8").strip('"`'))
        else:
            for child in node.children:
                walk(child)

    walk(tree.root_node)
    return sorted(list(set(imports)))


def _extract_ts_imports(file_path: Path) -> List[str]:
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
    imports = []

    def walk(node):
        if node.type == "import_statement":
            source_node = node.child_by_field_name("source")
            if source_node:
                imports.append(source_node.text.decode("utf-8").strip('"`'))
            else:
                for child in node.children:
                    if child.type == "string":
                        imports.append(child.text.decode("utf-8").strip('"`'))
        elif node.type == "call_expression":
            func = node.child_by_field_name("function")
            if func and func.text.decode("utf-8") in ("import", "require"):
                args = node.child_by_field_name("arguments")
                if args:
                    for child in args.children:
                        if child.type == "string":
                            imports.append(child.text.decode("utf-8").strip('"`'))
        else:
            for child in node.children:
                walk(child)

    walk(tree.root_node)
    return sorted(list(set(imports)))
