"""Issue #24 — TypeScript/JavaScript Tree-sitter scanner.

Scans TypeScript and JavaScript source files for log calls using Tree-sitter.
Supports: console.*, winston, pino, bunyan, NestJS Logger, log4js.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from .base import LogCallSite
from .queries.ts_logs import TS_LOGS_QUERY

# ── Valid TS/JS log methods (manual predicate enforcement) ────────────────────
_VALID_TS_LOG_METHODS = frozenset({
    "log", "info", "warn", "error", "debug",
    "trace", "fatal", "verbose", "silly",
})

# ── Level normalization ───────────────────────────────────────────────────────
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

# Template literal interpolation: ${expression} → {}
_TEMPLATE_INTERP_RE = re.compile(r'\$\{[^}]*\}')


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
                try:
                    self.ts_language = Language(ts_typescript.language_typescript())
                except TypeError:
                    self.ts_language = Language(ts_typescript.language_typescript(), "typescript")
                self.ts_parser = Parser(self.ts_language)
                self.ts_query = Query(self.ts_language, TS_LOGS_QUERY)
                self._ts_available = True
            except (ImportError, Exception):
                pass

            # Try JavaScript grammar
            try:
                import tree_sitter_javascript as ts_javascript
                try:
                    self.js_language = Language(ts_javascript.language())
                except TypeError:
                    self.js_language = Language(ts_javascript.language(), "javascript")
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

        try:
            with open(file_path, "rb") as f:
                source = f.read()
        except (IOError, OSError):
            return []

        try:
            from tree_sitter import QueryCursor
        except ImportError:
            QueryCursor = None

        tree = parser.parse(source)
        if QueryCursor is not None:
            cursor = QueryCursor(query)
            matches = cursor.matches(tree.root_node)
        else:
            matches = query.matches(tree.root_node)

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
            ctx = self._get_lexical_context(method_node)

            sites.append(LogCallSite(
                file_path=str(file_path),
                module_path=self._get_module_path(file_path),
                class_name=ctx.get("class_name"),
                function_name=ctx.get("function") or "<module>",
                log_level=level,
                message_template=message,
                line=line,
                column=method_node.start_point.column,
                lexical_context=ctx,
            ))

        return sites

    # ── String extraction ─────────────────────────────────────────────────────

    def _extract_string(self, node, source: bytes) -> str:
        """Extract a message template from a JS/TS string, template literal, or expression."""
        text = node.text.decode("utf-8")

        if node.type == "string":
            # Strip surrounding quotes — handles both single and double
            if len(text) >= 2:
                return text[1:-1]
            return text

        if node.type == "template_string":
            # Template literals: `hello ${name}` → "hello {}"
            result = text.strip('`')
            result = _TEMPLATE_INTERP_RE.sub('{}', result)
            return result

        # String concatenation: "a" + variable + "b"
        if node.type == "binary_expression":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            op = node.child_by_field_name("operator")
            if left and right and op and op.text == b"+":
                return self._extract_string(left, source) + self._extract_string(right, source)

        # Variable or expression → placeholder
        if node.type in ("identifier", "member_expression", "call_expression",
                         "new_expression", "await_expression", "number",
                         "true", "false", "null", "undefined"):
            return "{}"

        # Fallback: strip quotes
        if len(text) >= 2 and text[0] in ('"', "'", '`') and text[-1] == text[0]:
            return text[1:-1]
        return text

    # ── Lexical context ───────────────────────────────────────────────────────

    def _get_lexical_context(self, node) -> dict:
        """Walk up the AST to extract full lexical context.

        Detects:
          - function_declaration / method_definition / arrow_function
          - class_declaration / class expression
          - try_statement / catch_clause
          - if_statement
          - for / for_in / for_of / while / do loops
          - switch_statement
          - nested closures (in_closure)
          - async functions
        """
        enclosing_func = None
        class_name = None
        in_try = False
        in_catch = False
        in_if = False
        in_loop = False
        in_switch = False
        is_async = False
        in_closure = False

        parent = node.parent
        while parent:
            ptype = parent.type

            # Function declarations: function foo() {}
            if ptype == "function_declaration":
                if not enclosing_func:
                    name_node = parent.child_by_field_name("name")
                    if name_node:
                        enclosing_func = name_node.text.decode("utf-8")
                    # Check for async
                    for child in parent.children:
                        if child.type == "async":
                            is_async = True
                else:
                    in_closure = True

            # Method definitions: class Foo { bar() {} }
            elif ptype == "method_definition":
                if not enclosing_func:
                    name_node = parent.child_by_field_name("name")
                    if name_node:
                        enclosing_func = name_node.text.decode("utf-8")
                else:
                    in_closure = True

            # Arrow functions: const foo = () => {}
            elif ptype == "arrow_function":
                if not enclosing_func:
                    # Arrow functions assigned to const/let/var
                    if parent.parent and parent.parent.type == "variable_declarator":
                        name_node = parent.parent.child_by_field_name("name")
                        if name_node:
                            enclosing_func = name_node.text.decode("utf-8")
                    # Object property: { handler: () => {} }
                    elif parent.parent and parent.parent.type == "pair":
                        key_node = parent.parent.child_by_field_name("key")
                        if key_node:
                            enclosing_func = key_node.text.decode("utf-8")
                    for child in parent.children:
                        if child.type == "async":
                            is_async = True
                else:
                    in_closure = True

            # Anonymous functions: function() {}
            elif ptype == "function":
                if not enclosing_func:
                    name_node = parent.child_by_field_name("name")
                    if name_node:
                        enclosing_func = name_node.text.decode("utf-8")
                    elif parent.parent and parent.parent.type == "variable_declarator":
                        name_node = parent.parent.child_by_field_name("name")
                        if name_node:
                            enclosing_func = name_node.text.decode("utf-8")
                else:
                    in_closure = True

            # Class declarations
            elif ptype == "class_declaration":
                if not class_name:
                    name_node = parent.child_by_field_name("name")
                    if name_node:
                        class_name = name_node.text.decode("utf-8")

            # Class body (for class expressions)
            elif ptype == "class":
                if not class_name:
                    name_node = parent.child_by_field_name("name")
                    if name_node:
                        class_name = name_node.text.decode("utf-8")

            # Control flow
            elif ptype == "try_statement":
                in_try = True
            elif ptype == "catch_clause":
                in_catch = True
                in_try = True  # catch is part of try semantics
            elif ptype == "if_statement":
                in_if = True
            elif ptype in ("for_statement", "for_in_statement", "while_statement",
                           "do_statement"):
                in_loop = True
            elif ptype == "switch_statement":
                in_switch = True

            parent = parent.parent

        # Qualify with class name if present
        qualified = enclosing_func
        if class_name and enclosing_func:
            qualified = class_name + "." + enclosing_func

        return {
            "enclosing_function": enclosing_func,
            "function": qualified or enclosing_func,
            "class_name": class_name,
            "in_try_except": in_try,
            "in_catch": in_catch,
            "in_if_block": in_if,
            "in_loop": in_loop,
            "in_switch": in_switch,
            "is_async": is_async,
            "in_closure": in_closure,
        }

    # ── Module path ───────────────────────────────────────────────────────────

    def _get_module_path(self, file_path: Path) -> str:
        """Infer a module path from the TS/JS file path."""
        parts = list(file_path.with_suffix("").parts)
        for marker in ("src", "lib", "app", "pages", "components", "api"):
            if marker in parts:
                idx = parts.index(marker)
                return "/".join(parts[idx:])
        return "/".join(parts[-3:])
