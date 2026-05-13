"""Issue #23 — Go Tree-sitter scanner.

Scans Go source files for log calls using Tree-sitter queries.
Supports: stdlib log, slog, zap, logrus, zerolog.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .base import LogCallSite
from .queries.go_logs import GO_LOGS_QUERY

# Valid Go log methods (manual predicate enforcement)
_VALID_GO_LOG_METHODS = frozenset({
    "Debug", "Debugf", "Debugw", "Debugln",
    "Info", "Infof", "Infow", "Infoln",
    "Warn", "Warnf", "Warnw", "Warnln",
    "Error", "Errorf", "Errorw", "Errorln",
    "Fatal", "Fatalf", "Fatalw", "Fatalln",
    "Panic", "Panicf", "Panicln",
    "Print", "Printf", "Println",
    "Log", "Logf",
})

# Map Go method names to normalized log levels
_GO_LEVEL_MAP = {
    "Debug": "debug", "Debugf": "debug", "Debugw": "debug", "Debugln": "debug",
    "Info": "info", "Infof": "info", "Infow": "info", "Infoln": "info",
    "Warn": "warning", "Warnf": "warning", "Warnw": "warning", "Warnln": "warning",
    "Error": "error", "Errorf": "error", "Errorw": "error", "Errorln": "error",
    "Fatal": "critical", "Fatalf": "critical", "Fatalw": "critical", "Fatalln": "critical",
    "Panic": "critical", "Panicf": "critical", "Panicln": "critical",
    "Print": "info", "Printf": "info", "Println": "info",
    "Log": "info", "Logf": "info",
}


class GoScanner:
    """Tree-sitter-based scanner for Go log calls."""

    def __init__(self):
        try:
            import tree_sitter_go as tsgo
            from tree_sitter import Language, Parser, Query
            self.language = Language(tsgo.language())
            self.parser = Parser(self.language)
            self.query = Query(self.language, GO_LOGS_QUERY)
            self._available = True
        except ImportError:
            self._available = False

    @property
    def available(self) -> bool:
        """Whether the tree-sitter-go package is installed."""
        return self._available

    def scan_file(self, file_path: Path) -> List[LogCallSite]:
        """Scan a Go source file for log calls."""
        if not self._available:
            return []
        if not file_path.suffix == ".go":
            return []

        with open(file_path, "rb") as f:
            source = f.read()

        from tree_sitter import QueryCursor

        tree = self.parser.parse(source)
        cursor = QueryCursor(self.query)
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

            if method_name not in _VALID_GO_LOG_METHODS:
                continue

            line = method_node.start_point.row + 1
            if line in seen_lines:
                continue
            seen_lines.add(line)

            level = _GO_LEVEL_MAP.get(method_name, "info")
            message = self._extract_string(first_arg_node, source)
            enclosing_func, in_if, in_loop = self._get_lexical_context(method_node)

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
                    "in_if_block": in_if,
                    "in_loop": in_loop,
                },
            ))

        return sites

    def _extract_string(self, node, source: bytes) -> str:
        """Extract a message template from a Go string literal or expression."""
        import re
        text = node.text.decode("utf-8")

        if node.type == "interpreted_string_literal":
            result = text.strip('"')
        elif node.type == "raw_string_literal":
            result = text.strip('`')
        elif node.type == "identifier":
            return "{}"  # Variable reference
        else:
            result = text.strip('"').strip('`')

        # Normalize Go format verbs (%s, %d, %v, etc.) → {}
        result = re.sub(r'%[+\-#0 ]*(?:\d+)?(?:\.\d+)?[sdvfteqxXoObBpTwgGeE]', '{}', result)
        return result

    def _get_lexical_context(self, node):
        """Walk up the AST to find the enclosing function."""
        enclosing_func = None
        in_if = False
        in_loop = False

        parent = node.parent
        while parent:
            if parent.type == "function_declaration":
                if not enclosing_func:
                    name_node = parent.child_by_field_name("name")
                    if name_node:
                        enclosing_func = name_node.text.decode("utf-8")
            elif parent.type == "method_declaration":
                if not enclosing_func:
                    name_node = parent.child_by_field_name("name")
                    if name_node:
                        enclosing_func = name_node.text.decode("utf-8")
            elif parent.type == "if_statement":
                in_if = True
            elif parent.type in ("for_statement",):
                in_loop = True
            parent = parent.parent

        return enclosing_func, in_if, in_loop

    def _get_module_path(self, file_path: Path) -> str:
        """Infer a module path from the Go file path."""
        parts = list(file_path.with_suffix("").parts)
        # Use last 3 segments or from 'cmd'/'internal'/'pkg' onwards
        for marker in ("cmd", "internal", "pkg"):
            if marker in parts:
                idx = parts.index(marker)
                return "/".join(parts[idx:])
        return "/".join(parts[-3:])
