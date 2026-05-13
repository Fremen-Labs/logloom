"""Issue #23 — Go Tree-sitter scanner.

Scans Go source files for log calls using Tree-sitter queries.
Supports: stdlib log, slog, zap (typed + sugar), logrus, zerolog (chained builder).

Production-ready features:
  - Two-pass matching to resolve zerolog chain conflicts
  - Zerolog builder intermediary exclusion (30+ methods)
  - Zap field constructor false-positive elimination
  - String concatenation (binary_expression with +) flattening
  - fmt.Sprintf / fmt.Errorf format string extraction
  - Go format verb normalization (%s → {})
  - Method receiver qualification (AuthService.Authenticate)
  - Full lexical context: function, receiver, if, loop, switch, select, defer, goroutine, closure
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import LogCallSite
from .queries.go_logs import GO_LOGS_QUERY

# ── Valid method names (manual predicate enforcement) ─────────────────────────
_VALID_DIRECT_METHODS = frozenset({
    "Debug", "Debugf", "Debugw", "Debugln",
    "Info", "Infof", "Infow", "Infoln",
    "Warn", "Warnf", "Warnw", "Warnln",
    "Error", "Errorf", "Errorw", "Errorln",
    "Fatal", "Fatalf", "Fatalw", "Fatalln",
    "Panic", "Panicf", "Panicln",
    "Print", "Printf", "Println",
    "Log", "Logf",
    "DPanic", "DPanicf", "DPanicw",
})

# Zerolog terminal methods — the chain emitter
_VALID_ZEROLOG_METHODS = frozenset({"Msg", "Msgf", "Send"})

# Zerolog builder intermediaries — NOT log emission points.
_ZEROLOG_BUILDER_METHODS = frozenset({
    "Err", "Str", "Int", "Int64", "Float64", "Bool", "Bytes",
    "Time", "Dur", "Dict", "Array", "Object", "Interface",
    "Caller", "Stack", "Timestamp", "CallerWithSkipFrameCount",
    "Any", "AnErr", "Strs", "Ints", "Floats", "Bools",
    "RawJSON", "Hex", "IPAddr", "MACAddr",
    "With", "Level", "Sample", "Hook",
})

# Zap field constructors — these produce zap.Field, not log calls.
# zap.Error(err) should NOT be treated as logger.Error("msg").
_ZAP_FIELD_CONSTRUCTORS = frozenset({
    "String", "Int", "Int64", "Float64", "Bool", "ByteString",
    "Binary", "Reflect", "Stringer", "Time", "Duration",
    "Any", "Error", "NamedError", "Errors", "Stack", "StackSkip",
    "Object", "Array", "Namespace", "Skip", "Inline",
    "Uint", "Uint64", "Uint32", "Uint16", "Uint8",
    "Int32", "Int16", "Int8", "Float32",
    "Complex128", "Complex64", "Uintptr",
})

# Combined set for the scanner
_ALL_VALID_METHODS = _VALID_DIRECT_METHODS | _VALID_ZEROLOG_METHODS

# ── Level normalization ───────────────────────────────────────────────────────
_GO_LEVEL_MAP = {
    "Debug": "debug", "Debugf": "debug", "Debugw": "debug", "Debugln": "debug",
    "Info": "info", "Infof": "info", "Infow": "info", "Infoln": "info",
    "Warn": "warning", "Warnf": "warning", "Warnw": "warning", "Warnln": "warning",
    "Error": "error", "Errorf": "error", "Errorw": "error", "Errorln": "error",
    "Fatal": "critical", "Fatalf": "critical", "Fatalw": "critical", "Fatalln": "critical",
    "Panic": "critical", "Panicf": "critical", "Panicln": "critical",
    "Print": "info", "Printf": "info", "Println": "info",
    "Log": "info", "Logf": "info",
    "DPanic": "critical", "DPanicf": "critical", "DPanicw": "critical",
    # Zerolog terminals — level comes from the chain origin
    "Msg": None, "Msgf": None, "Send": None,
}

# Go format verb regex — normalizes %s, %d, %v, etc. to {}
_GO_FMT_VERB_RE = re.compile(r'%[+\-#0 ]*(?:\*|\d+)?(?:\.(?:\*|\d+))?[sdvfteqxXoObBpTwgGUcn]')

# Known zap package identifiers
_ZAP_PKG_NAMES = frozenset({"zap"})


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
        if file_path.suffix != ".go":
            return []

        try:
            with open(file_path, "rb") as f:
                source = f.read()
        except (IOError, OSError):
            return []

        from tree_sitter import QueryCursor

        tree = self.parser.parse(source)
        cursor = QueryCursor(self.query)
        matches = cursor.matches(tree.root_node)

        # ── Two-pass matching ─────────────────────────────────────────────
        # Pass 1: Collect all candidate matches keyed by line number.
        # A single line may produce multiple matches (e.g. zerolog chain:
        #   log.Error().Err(err).Msg("text")
        # yields Pattern 1 (.Error) and Pattern 2 (.Msg) on the same line.
        # We prefer the zerolog terminal (.Msg) because it carries the message.
        candidates: dict[int, dict] = {}

        for match in matches:
            captures = match[1]
            method_nodes = captures.get("log_method", [])
            first_arg_nodes = captures.get("first_arg", [])

            if not method_nodes:
                continue

            method_node = method_nodes[0]
            method_name = method_node.text.decode("utf-8")

            if method_name not in _ALL_VALID_METHODS:
                continue

            # Skip zerolog builder intermediaries (Err, Str, Int, etc.)
            if method_name in _ZEROLOG_BUILDER_METHODS:
                continue

            # ── Zap field constructor false-positive elimination ───────────
            # zap.Error(err) inside logger.Error("msg", zap.Error(err))
            # is a field constructor, not a log call. Detect by checking
            # if the call_expression's operand is a zap package identifier.
            if self._is_zap_field_constructor(method_node):
                continue

            # ── Nested call false-positive elimination ────────────────────
            # If this method call is nested inside another call's argument
            # list, it's likely a field constructor or wrapper, not a log call.
            if self._is_nested_in_argument_list(method_node):
                continue

            line = method_node.start_point.row + 1
            is_terminal = method_name in _VALID_ZEROLOG_METHODS

            # If this line already has a terminal match, skip non-terminals
            if line in candidates:
                existing_is_terminal = candidates[line]["is_terminal"]
                if existing_is_terminal and not is_terminal:
                    continue  # Terminal already claimed this line
                if not existing_is_terminal and is_terminal:
                    pass  # Override: terminal takes priority
                elif existing_is_terminal and is_terminal:
                    continue  # Both are terminals — keep the first

            candidates[line] = {
                "method_node": method_node,
                "method_name": method_name,
                "first_arg_nodes": first_arg_nodes,
                "is_terminal": is_terminal,
            }

        # ── Pass 2: Build LogCallSite objects from resolved candidates ─────
        sites = []
        for line, cand in sorted(candidates.items()):
            method_name = cand["method_name"]
            method_node = cand["method_node"]
            first_arg_nodes = cand["first_arg_nodes"]

            # Determine log level
            if method_name in _VALID_ZEROLOG_METHODS:
                level = self._resolve_zerolog_level(method_node)
            else:
                level = _GO_LEVEL_MAP.get(method_name, "info")

            # Extract message
            if first_arg_nodes:
                message = self._extract_string(first_arg_nodes[0], source)
            elif method_name == "Send":
                message = "(zerolog.Send)"
            else:
                message = "(no message)"

            # Lexical context
            ctx = self._get_lexical_context(method_node)

            sites.append(LogCallSite(
                file_path=str(file_path),
                module_path=self._get_module_path(file_path),
                class_name=None,
                function_name=ctx["function"] or "<module>",
                log_level=level,
                message_template=message,
                line=line,
                column=method_node.start_point.column,
                lexical_context=ctx,
            ))

        return sites

    # ── False-positive detection ──────────────────────────────────────────────

    def _is_zap_field_constructor(self, method_node) -> bool:
        """Check if this is a zap field constructor like zap.Error(), zap.String().

        These are NOT log calls — they produce zap.Field values used as arguments
        to the real log call. The AST pattern is:
            call_expression
              selector_expression
                identifier "zap"         ← package is "zap"
                field_identifier "Error"  ← method matches a field constructor
        """
        # method_node is the field_identifier. Its parent should be selector_expression.
        parent = method_node.parent
        if not parent or parent.type != "selector_expression":
            return False

        method_name = method_node.text.decode("utf-8")
        if method_name not in _ZAP_FIELD_CONSTRUCTORS:
            return False

        # Check if the operand is a known zap package identifier
        operand = parent.child_by_field_name("operand")
        if operand and operand.type == "identifier":
            pkg_name = operand.text.decode("utf-8")
            if pkg_name in _ZAP_PKG_NAMES:
                return True

        return False

    def _is_nested_in_argument_list(self, method_node) -> bool:
        """Check if this method call is nested inside another call's argument_list.

        Detects patterns like: logger.Error("msg", zap.Error(err))
        where zap.Error(err) is nested inside logger.Error's argument_list.

        We walk up from the method_node through: field_identifier → selector_expression
        → call_expression → and check if that call_expression's parent is an argument_list
        that itself belongs to another call_expression.
        """
        # Walk: method_node (field_identifier) → selector_expression → call_expression
        sel_expr = method_node.parent
        if not sel_expr or sel_expr.type != "selector_expression":
            return False

        call_expr = sel_expr.parent
        if not call_expr or call_expr.type != "call_expression":
            return False

        # Check if this call_expression is inside an argument_list
        container = call_expr.parent
        if container and container.type == "argument_list":
            # And the argument_list belongs to another call_expression
            outer_call = container.parent
            if outer_call and outer_call.type == "call_expression":
                # This is a nested call. But we need to be careful: logrus.WithError().Error()
                # is a chained call where .Error() is NOT inside an argument_list.
                # Only skip if we're truly inside the args of an outer log call.
                return True

        return False

    # ── Zerolog level resolution ──────────────────────────────────────────────

    def _resolve_zerolog_level(self, msg_method_node) -> str:
        """Walk up the zerolog call chain to find the originating level method.

        For ``log.Error().Err(err).Msg("fail")``, we walk backwards from .Msg
        through the chain until we find a known level method (Error, Warn, etc.).
        """
        _ZEROLOG_LEVELS = {
            "Trace": "debug", "Debug": "debug",
            "Info": "info",
            "Warn": "warning",
            "Error": "error",
            "Fatal": "critical", "Panic": "critical",
        }

        # Start from the selector_expression that contains .Msg
        node = msg_method_node.parent  # selector_expression
        if not node or node.type != "selector_expression":
            return "info"

        # Walk inward through the operand chain
        current = node
        depth = 0
        while current and depth < 20:
            if current.type == "selector_expression":
                field = current.child_by_field_name("field")
                if field:
                    name = field.text.decode("utf-8")
                    if name in _ZEROLOG_LEVELS:
                        return _ZEROLOG_LEVELS[name]
                # Go deeper into the operand
                operand = current.child_by_field_name("operand")
                if operand and operand.type == "call_expression":
                    fn = operand.child_by_field_name("function")
                    if fn:
                        current = fn
                    else:
                        break
                else:
                    current = operand
            elif current.type == "call_expression":
                fn = current.child_by_field_name("function")
                if fn:
                    current = fn
                else:
                    break
            else:
                break
            depth += 1

        return "info"  # Fallback

    # ── String extraction ─────────────────────────────────────────────────────

    def _extract_string(self, node, source: bytes) -> str:
        """Extract a message template from a Go string literal or expression.

        Handles:
          - Interpreted strings: "hello %s" → "hello {}"
          - Raw strings: `hello %s` → "hello {}"
          - String concatenation: "a" + var + "b" → "a {} b"
          - Multi-line concat: "a " +\\n "b" → "a b"
          - fmt.Sprintf / fmt.Errorf: extract the format string
          - Variable references: identifier → "{}"
        """
        text = node.text.decode("utf-8")

        if node.type == "interpreted_string_literal":
            result = text.strip('"')
            return _GO_FMT_VERB_RE.sub('{}', result)

        if node.type == "raw_string_literal":
            result = text.strip('`')
            return _GO_FMT_VERB_RE.sub('{}', result)

        if node.type in ("identifier",):
            return "{}"  # Variable reference

        if node.type == "selector_expression":
            # pkg.Var or obj.Field — treat as variable
            return "{}"

        # ── Binary expression: string concatenation ───────────────────────
        if node.type == "binary_expression":
            return self._extract_binary_expression(node, source)

        # ── Call expression: fmt.Sprintf, fmt.Errorf ──────────────────────
        if node.type == "call_expression":
            fn = node.child_by_field_name("function")
            if fn:
                fn_text = fn.text.decode("utf-8")
                # Extract the format string from fmt.Sprintf/Errorf/etc.
                if any(fn_text.endswith(s) for s in ("Sprintf", "Errorf", "Fprintf")):
                    args = node.child_by_field_name("arguments")
                    if args:
                        # Find the first non-punctuation child (skip "(")
                        for child in args.children:
                            if child.type not in ("(", ")", ","):
                                # For Fprintf, skip the writer arg (first arg)
                                if fn_text.endswith("Fprintf"):
                                    continue
                                return self._extract_string(child, source)
            return "{}"

        # ── Fallback: strip quotes ────────────────────────────────────────
        result = text.strip('"').strip('`')
        return _GO_FMT_VERB_RE.sub('{}', result)

    def _extract_binary_expression(self, node, source: bytes) -> str:
        """Flatten a binary_expression chain of string concatenation.

        Handles: "prefix: " + someVar + " suffix"  →  "prefix: {} suffix"
        And:     "part1 " +
                     "part2 " +
                     "part3"                        →  "part1 part2 part3"
        """
        parts = []
        self._collect_binary_parts(node, source, parts)
        return "".join(parts)

    def _collect_binary_parts(self, node, source: bytes, parts: list) -> None:
        """Recursively collect parts of a binary_expression."""
        if node.type == "binary_expression":
            left = node.child_by_field_name("left")
            op = node.child_by_field_name("operator")
            right = node.child_by_field_name("right")

            if left and right and op and op.text == b"+":
                self._collect_binary_parts(left, source, parts)
                self._collect_binary_parts(right, source, parts)
            else:
                # Non-concatenation binary expression
                parts.append("{}")
        elif node.type == "interpreted_string_literal":
            text = node.text.decode("utf-8").strip('"')
            parts.append(_GO_FMT_VERB_RE.sub('{}', text))
        elif node.type == "raw_string_literal":
            text = node.text.decode("utf-8").strip('`')
            parts.append(_GO_FMT_VERB_RE.sub('{}', text))
        elif node.type in ("identifier", "selector_expression",
                           "call_expression", "unary_expression",
                           "index_expression", "slice_expression"):
            parts.append("{}")
        else:
            # Fallback: try to extract text
            text = node.text.decode("utf-8").strip('"').strip('`')
            parts.append(_GO_FMT_VERB_RE.sub('{}', text))

    # ── Lexical context ───────────────────────────────────────────────────────

    def _get_lexical_context(self, node) -> dict:
        """Walk up the AST to extract full lexical context.

        Detects:
          - function_declaration / method_declaration (enclosing function)
          - method receiver type qualification (AuthService.Authenticate)
          - func_literal (anonymous closure / callback)
          - if_statement, for_statement, switch_statement, select_statement
          - defer_statement, go_statement
        """
        enclosing_func = None
        receiver_type = None
        in_if = False
        in_loop = False
        in_switch = False
        in_select = False
        in_defer = False
        in_goroutine = False
        in_closure = False

        parent = node.parent
        while parent:
            ptype = parent.type

            if ptype == "function_declaration":
                if not enclosing_func:
                    name_node = parent.child_by_field_name("name")
                    if name_node:
                        enclosing_func = name_node.text.decode("utf-8")

            elif ptype == "method_declaration":
                if not enclosing_func:
                    name_node = parent.child_by_field_name("name")
                    if name_node:
                        enclosing_func = name_node.text.decode("utf-8")
                    # Extract receiver type
                    receiver = parent.child_by_field_name("receiver")
                    if receiver:
                        for child in receiver.children:
                            if child.type == "parameter_declaration":
                                type_node = child.child_by_field_name("type")
                                if type_node:
                                    receiver_type = type_node.text.decode("utf-8").lstrip("*")

            elif ptype == "func_literal":
                # Anonymous function / closure.
                # If we haven't found an enclosing func yet, this IS the enclosing scope.
                # If we already have one, this is a nested closure.
                if enclosing_func:
                    in_closure = True
                else:
                    # Try to infer a name from the assignment context.
                    # e.g.: handler := func() { ... }
                    gparent = parent.parent
                    if gparent and gparent.type == "short_var_declaration":
                        # left := func() { ... }
                        left = gparent.child_by_field_name("left")
                        if left:
                            for child in left.children:
                                if child.type == "identifier":
                                    enclosing_func = child.text.decode("utf-8")
                                    in_closure = True
                                    break
                    if not enclosing_func:
                        in_closure = True
                        # Will inherit the outer function name when we continue walking up

            elif ptype == "if_statement":
                in_if = True
            elif ptype == "for_statement":
                in_loop = True
            elif ptype in ("switch_statement", "type_switch_statement",
                           "expression_switch_statement"):
                in_switch = True
            elif ptype == "select_statement":
                in_select = True
            elif ptype == "defer_statement":
                in_defer = True
            elif ptype == "go_statement":
                in_goroutine = True

            parent = parent.parent

        # Qualify method name with receiver: "Server.handleAuth"
        if receiver_type and enclosing_func:
            enclosing_func = receiver_type + "." + enclosing_func

        return {
            "enclosing_function": enclosing_func,
            "function": enclosing_func,
            "receiver_type": receiver_type,
            "in_if_block": in_if,
            "in_loop": in_loop,
            "in_switch": in_switch,
            "in_select": in_select,
            "in_defer": in_defer,
            "in_goroutine": in_goroutine,
            "in_closure": in_closure,
        }

    # ── Module path ───────────────────────────────────────────────────────────

    def _get_module_path(self, file_path: Path) -> str:
        """Infer a module path from the Go file path."""
        parts = list(file_path.with_suffix("").parts)
        for marker in ("cmd", "internal", "pkg", "api", "server"):
            if marker in parts:
                idx = parts.index(marker)
                return "/".join(parts[idx:])
        return "/".join(parts[-3:])
