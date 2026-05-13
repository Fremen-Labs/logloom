"""Issue #24 — TypeScript Tree-sitter scanner.

Scans TypeScript and JavaScript source files for log calls using Tree-sitter.
Supports: console.*, winston, pino, bunyan.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .base import LogCallSite
from .queries.ts_logs import TS_LOGS_QUERY

# Valid TS/JS log methods (manual predicate enforcement)
_VALID_TS_LOG_METHODS = frozenset({
    "log", "info", "warn", "error", "debug",
    "trace", "fatal", "verbose", "silly",
})

# Map JS/TS method names to normalized log levels
_TS_LEVEL_MAP = {
    "log": "info",
    "info": "info",
    "warn": "warning",
    "error": "error",
    "debug": "debug",
    "trace": "debug",
    "fatal": "critical",
    "verbose": "debug",
    "silly": "debug",
}


class TypeScriptScanner:
    """Tree-sitter-based scanner for TypeScript/JavaScript log calls."""

    def __init__(self):
        self._available = False
        self._ts_available = False
        self._js_available = False

        try:
            from tree_sitter import Language, Parser, Query

            # Try TypeScript grammar first
            try:
                import tree_sitter_typescript as ts_typescript
                self.ts_language = Language(ts_typescript.language_typescript())
                self.ts_parser = Parser(self.ts_language)
                self.ts_query = Query(self.ts_language, TS_LOGS_QUERY)
                self._ts_available = True
            except (ImportError, Exception):
                pass

            # Try JavaScript grammar
            try:
                import tree_sitter_javascript as ts_javascript
                self.js_language = Language(ts_javascript.language())
                self.js_parser = Parser(self.js_language)
                self.js_query = Query(self.js_language, TS_LOGS_QUERY)
                self._js_available = True
            except (ImportError, Exception):
                pass

            self._available = self._ts_available or self._js_available
        except ImportError:
            pass

    @property
    def available(self) -> bool:
        return self._available

    def scan_file(self, file_path: Path) -> List[LogCallSite]:
        """Scan a TypeScript or JavaScript source file for log calls."""
        if not self._available:
            return []

        suffix = file_path.suffix
        if suffix in (".ts", ".tsx") and self._ts_available:
            parser = self.ts_parser
            query = self.ts_query
        elif suffix in (".js", ".jsx", ".mjs", ".cjs"):
            if self._js_available:
                parser = self.js_parser
                query = self.js_query
            elif self._ts_available:
                # TypeScript parser can handle JavaScript
                parser = self.ts_parser
                query = self.ts_query
            else:
                return []
        else:
            return []

        with open(file_path, "rb") as f:
            source = f.read()

        from tree_sitter import QueryCursor

        tree = parser.parse(source)
        cursor = QueryCursor(query)
        matches = cursor.matches(tree.root_node)

        sites = []
        seen_lines = set()

        for match in matches:
            captures = match[1]
            method_nodes = captures.get("log_method", [])
            first_arg_nodes = captures.get("first_arg", [])

            if not method_nodes or not first_arg_nodes:
                continue

            method_node = method_nodes[0]
            first_arg_node = first_arg_nodes[0]
            method_name = method_node.text.decode("utf-8")

            if method_name not in _VALID_TS_LOG_METHODS:
                continue

            line = method_node.start_point.row + 1
            if line in seen_lines:
                continue
            seen_lines.add(line)

            level = _TS_LEVEL_MAP.get(method_name, "info")
            message = self._extract_string(first_arg_node, source)
            enclosing_func = self._get_enclosing_function(method_node)

            sites.append(LogCallSite(
                file_path=str(file_path),
                module_path=self._get_module_path(file_path),
                class_name=None,
                function_name=enclosing_func or "<module>",
                log_level=level,
                message_template=message,
                line=line,
                column=method_node.start_point.column,
                lexical_context={
                    "enclosing_function": enclosing_func,
                },
            ))

        return sites

    def _extract_string(self, node, source: bytes) -> str:
        """Extract a message template from a JS/TS string, template literal, or expression."""
        text = node.text.decode("utf-8")

        if node.type == "string":
            # Strip surrounding quotes
            return text.strip('"').strip("'")

        if node.type == "template_string":
            # Template literals: `hello ${name}` → "hello {}"
            import re
            result = text.strip('`')
            result = re.sub(r'\$\{[^}]*\}', '{}', result)
            return result

        # Variable or expression → placeholder
        if node.type in ("identifier", "member_expression", "call_expression"):
            return "{}"

        # Fallback: strip quotes
        return text.strip('"').strip("'").strip('`')

    def _get_enclosing_function(self, node) -> Optional[str]:
        """Walk up the AST to find the enclosing function."""
        parent = node.parent
        while parent:
            if parent.type in (
                "function_declaration", "method_definition",
                "arrow_function", "function",
            ):
                name_node = parent.child_by_field_name("name")
                if name_node:
                    return name_node.text.decode("utf-8")
                # For arrow functions assigned to a variable
                if parent.parent and parent.parent.type == "variable_declarator":
                    name_node = parent.parent.child_by_field_name("name")
                    if name_node:
                        return name_node.text.decode("utf-8")
            parent = parent.parent
        return None

    def _get_module_path(self, file_path: Path) -> str:
        """Infer a module path from the TS/JS file path."""
        parts = list(file_path.with_suffix("").parts)
        for marker in ("src", "lib", "app"):
            if marker in parts:
                idx = parts.index(marker)
                return "/".join(parts[idx:])
        return "/".join(parts[-3:])
