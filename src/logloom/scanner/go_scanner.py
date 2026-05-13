"""Issue #23 — Go Tree-sitter scanner.

Scans Go source files for log calls using Tree-sitter queries.
Supports: stdlib log, slog, zap (typed + sugar), logrus, zerolog (chained builder).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

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

# Zerolog builder intermediaries — these are NOT log emission points and must
# be filtered out when matched by Pattern 1 (the broad selector_expression query).
# Without this, log.Error().Err(err).Msg("text") would match .Err() as a
# false-positive log call with message "err" instead of the terminal .Msg().
_ZEROLOG_BUILDER_METHODS = frozenset({
    "Err", "Str", "Int", "Int64", "Float64", "Bool", "Bytes",
    "Time", "Dur", "Dict", "Array", "Object", "Interface",
    "Caller", "Stack", "Timestamp", "CallerWithSkipFrameCount",
    "Any", "AnErr", "Strs", "Ints", "Floats", "Bools",
    "RawJSON", "Hex", "IPAddr", "MACAddr",
    "With", "Level", "Sample", "Hook",
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

    # ── Zerolog level resolution ──────────────────────────────────────────────

    def _resolve_zerolog_level(self, msg_method_node) -> str:
        """Walk up the zerolog call chain to find the originating level method.

        For ``log.Error().Err(err).Msg("fail")``, the AST is:
            call_expression
              selector_expression
                call_expression          ← .Err(err)
                  selector_expression
                    call_expression      ← .Error()
                      selector_expression
                        identifier "log"
                        field_identifier "Error"
                  ...
                field_identifier "Msg"
              ...

        We walk the operand chain until we find a field_identifier that matches
        a known level name.
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
                    # The function of this call_expression
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
        """Extract a message template from a Go string literal or expression."""
        text = node.text.decode("utf-8")

        if node.type == "interpreted_string_literal":
            result = text.strip('"')
        elif node.type == "raw_string_literal":
            result = text.strip('`')
        elif node.type in ("identifier", "selector_expression"):
            return "{}"  # Variable reference
        elif node.type == "call_expression":
            # fmt.Sprintf("...", args) — extract the format string
            fn = node.child_by_field_name("function")
            if fn:
                fn_text = fn.text.decode("utf-8")
                if "Sprintf" in fn_text or "Errorf" in fn_text:
                    args = node.child_by_field_name("arguments")
                    if args and args.child_count > 1:
                        first = args.children[1]  # skip "("
                        return self._extract_string(first, source)
            return "{}"
        else:
            result = text.strip('"').strip('`')

        # Normalize Go format verbs (%s, %d, %v, etc.) → {}
        result = _GO_FMT_VERB_RE.sub('{}', result)
        return result

    # ── Lexical context ───────────────────────────────────────────────────────

    def _get_lexical_context(self, node) -> dict:
        """Walk up the AST to extract full lexical context."""
        enclosing_func = None
        receiver_type = None
        in_if = False
        in_loop = False
        in_select = False
        in_defer = False
        in_goroutine = False

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
                    # Extract receiver type — the receiver IS a parameter_list
                    # containing (parameter_declaration) children.
                    receiver = parent.child_by_field_name("receiver")
                    if receiver:
                        for child in receiver.children:
                            if child.type == "parameter_declaration":
                                type_node = child.child_by_field_name("type")
                                if type_node:
                                    receiver_type = type_node.text.decode("utf-8").lstrip("*")

            elif ptype == "if_statement":
                in_if = True
            elif ptype == "for_statement":
                in_loop = True
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
            "in_select": in_select,
            "in_defer": in_defer,
            "in_goroutine": in_goroutine,
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
