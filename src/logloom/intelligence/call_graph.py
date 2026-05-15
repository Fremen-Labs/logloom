"""Issue #15 — Inter-function call-graph edge resolution.

Walks the AST of Python and Go source files to build a mapping of which
functions call which other functions.  Then resolves those edges against the
set of functions that contain log sites, populating ``call_parents`` and
``call_children`` on the relevant GraphNodes.

Go support (Phase 4a) handles:
  - function_declaration → call_expression edges
  - method_declaration → call_expression edges (receiver-qualified)
  - go_statement (goroutine launch) edges
  - Receiver-qualified callee resolution (obj.Method → Type.Method)
"""

from __future__ import annotations

import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Query, QueryCursor
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ..graph.model import GraphNode, LogLoomGraph

# ── Tree-sitter query for Python function calls ──────────────────────────────

_CALL_IN_FUNCTION_QUERY = """
(call
  function: [
    (identifier) @callee
    (attribute attribute: (identifier) @callee)
  ]
) @call_site
"""


# ── Go-specific tree-sitter query for function calls ─────────────────────────
# Captures all call_expression nodes at any depth within function bodies.
# We then walk up to find the enclosing function/method declaration.
_GO_CALL_QUERY = """
(call_expression
  function: [
    (identifier) @callee
    (selector_expression
      operand: (_) @receiver
      field: (field_identifier) @callee_method
    )
  ]
) @go_call_site
"""


class CallGraphResolver:
    """Builds inter-function call edges from source AST and maps them to graph nodes.

    Supports both Python and Go source files.
    """

    def __init__(self):
        self.language = Language(tspython.language())
        self.parser = Parser(self.language)
        self._call_query = Query(self.language, _CALL_IN_FUNCTION_QUERY)

        # Go support (optional — requires tree_sitter_go)
        self._go_resolver: Optional[_GoCallGraphResolver] = None
        try:
            self._go_resolver = _GoCallGraphResolver()
        except ImportError:
            pass

    def resolve(
        self, graph: LogLoomGraph, source_paths: List[Path]
    ) -> LogLoomGraph:
        """Walk source files, build call edges, and enrich the graph.

        Returns a new graph with populated call_parents / call_children.
        """
        # Step 1: Build caller → {callees} map from ALL source files
        call_map: Dict[str, Set[str]] = {}

        for path in source_paths:
            if path.is_file():
                self._scan_file(path, call_map)
            elif path.is_dir():
                for src_file in path.rglob("*"):
                    self._scan_file(src_file, call_map)

        # Step 2: Identify which functions contain log sites (by function name)
        func_to_nodes: Dict[str, List[str]] = {}
        for node in graph.nodes.values():
            func_to_nodes.setdefault(node.function, []).append(node.node_id)

        # Step 3: For each node, populate call_parents and call_children
        new_nodes: Dict[str, GraphNode] = {}
        for node_id, node in graph.nodes.items():
            parents: Set[str] = set()
            children: Set[str] = set()

            # Find parent functions (functions that call this node's function)
            for caller, callees in call_map.items():
                if node.function in callees and caller != node.function:
                    for parent_node_id in func_to_nodes.get(caller, []):
                        parents.add(parent_node_id)

            # Find child functions (functions called by this node's function)
            for callee in call_map.get(node.function, set()):
                if callee != node.function:
                    for child_node_id in func_to_nodes.get(callee, []):
                        children.add(child_node_id)

            new_nodes[node_id] = node.model_copy(update={
                "call_parents": sorted(parents),
                "call_children": sorted(children),
            })

        return graph.model_copy(update={"nodes": new_nodes})

    def _scan_file(self, file_path: Path, call_map: Dict[str, Set[str]]):
        """Route a file to the correct language-specific scanner."""
        if file_path.suffix == ".py":
            self._extract_python_calls(file_path, call_map)
        elif file_path.suffix == ".go" and self._go_resolver:
            if not file_path.name.endswith("_test.go"):
                self._go_resolver.extract_calls(file_path, call_map)

    # ── Python call extraction ────────────────────────────────────────────────

    def _extract_python_calls(self, file_path: Path, call_map: Dict[str, Set[str]]):
        """Parse a Python file and populate the call_map."""
        try:
            with open(file_path, "rb") as f:
                source = f.read()
        except (IOError, OSError):
            return

        tree = self.parser.parse(source)
        self._walk_python_functions(tree.root_node, call_map, source)

    def _walk_python_functions(self, node, call_map: Dict[str, Set[str]], source: bytes):
        """Recursively find function_definitions and extract calls from their bodies."""
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                func_name = name_node.text.decode("utf-8")
                body = node.child_by_field_name("body")
                if body:
                    callees = self._extract_python_callees(body, source)
                    existing = call_map.get(func_name, set())
                    call_map[func_name] = existing | callees

        for child in node.children:
            self._walk_python_functions(child, call_map, source)

    def _extract_python_callees(self, body_node, source: bytes) -> Set[str]:
        """Use QueryCursor to find all function calls within a body node."""
        cursor = QueryCursor(self._call_query)
        matches = cursor.matches(body_node)

        callees: Set[str] = set()
        for _, captures in matches:
            callee_nodes = captures.get("callee", [])
            for callee_node in callee_nodes:
                callee_name = callee_node.text.decode("utf-8")
                if callee_name not in _PYTHON_BUILTIN_SKIP:
                    callees.add(callee_name)

        return callees


# ── Go call-graph resolver ────────────────────────────────────────────────────

# Go builtins and stdlib functions that don't produce meaningful edges
_GO_BUILTIN_SKIP = frozenset({
    # Language builtins
    "make", "len", "cap", "new", "append", "copy", "delete", "close",
    "panic", "recover", "complex", "real", "imag", "print", "println",
    "min", "max", "clear",
    # Common type conversions
    "string", "byte", "rune", "int", "int64", "int32", "float64", "float32",
    "uint", "uint64", "uint32", "bool",
    # Log methods themselves — already captured as graph nodes
    "Debug", "Debugf", "Debugw", "Debugln",
    "Info", "Infof", "Infow", "Infoln",
    "Warn", "Warnf", "Warnw", "Warnln",
    "Error", "Errorf", "Errorw", "Errorln",
    "Fatal", "Fatalf", "Fatalw", "Fatalln",
    "Panic", "Panicf", "Panicln",
    "Print", "Printf", "Println",
    "Log", "Logf",
})

# Packages whose method calls should NOT produce call edges
_GO_STDLIB_SKIP = frozenset({
    "fmt", "http", "json", "os", "io", "strings", "bytes", "strconv",
    "filepath", "errors", "context", "sync", "time", "sort", "math",
    "regexp", "encoding", "net", "crypto", "reflect", "testing",
    "slog", "log",
})


class _GoCallGraphResolver:
    """Tree-sitter-based call-graph resolver for Go source files.

    Extracts function/method declarations and the calls within them,
    producing caller → {callee, ...} edges that match the graph's
    receiver-qualified function names (e.g. "Server.handleAuth").
    """

    def __init__(self):
        import tree_sitter_go as tsgo
        self.language = Language(tsgo.language())
        self.parser = Parser(self.language)

    def extract_calls(self, file_path: Path, call_map: Dict[str, Set[str]]):
        """Parse a Go file and populate call_map with caller→callee edges."""
        try:
            with open(file_path, "rb") as f:
                source = f.read()
        except (IOError, OSError):
            return

        tree = self.parser.parse(source)
        self._walk_go_declarations(tree.root_node, call_map, source)

    def _walk_go_declarations(self, node, call_map: Dict[str, Set[str]], source: bytes):
        """Find function and method declarations, extract call edges from their bodies."""
        if node.type == "function_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                func_name = name_node.text.decode("utf-8")
                body = node.child_by_field_name("body")
                if body:
                    callees = self._extract_go_callees(body, source)
                    existing = call_map.get(func_name, set())
                    call_map[func_name] = existing | callees

        elif node.type == "method_declaration":
            name_node = node.child_by_field_name("name")
            receiver = node.child_by_field_name("receiver")
            if name_node:
                method_name = name_node.text.decode("utf-8")
                # Qualify with receiver type: Server.handleAuth
                receiver_type = self._extract_receiver_type(receiver)
                if receiver_type:
                    qualified = f"{receiver_type}.{method_name}"
                else:
                    qualified = method_name

                body = node.child_by_field_name("body")
                if body:
                    callees = self._extract_go_callees(body, source)
                    existing = call_map.get(qualified, set())
                    call_map[qualified] = existing | callees

        # Recurse into children (handles nested structures, init functions, etc.)
        for child in node.children:
            self._walk_go_declarations(child, call_map, source)

    def _extract_go_callees(self, body_node, source: bytes) -> Set[str]:
        """Walk a function body to find all call_expression and go_statement targets.

        Handles:
          - Direct calls:    someFunc(args)         → "someFunc"
          - Method calls:    obj.Method(args)       → "Method"  (bare)
          - Qualified calls: s.handleAuth(args)     → resolved via receiver type
          - Goroutine:       go worker.Process()    → "Process"
        """
        callees: Set[str] = set()
        self._walk_calls(body_node, callees, source)
        return callees

    def _walk_calls(self, node, callees: Set[str], source: bytes):
        """Recursively walk the AST to find call targets."""
        if node.type == "call_expression":
            fn = node.child_by_field_name("function")
            if fn:
                callee = self._resolve_callee(fn, source)
                if callee and callee not in _GO_BUILTIN_SKIP:
                    callees.add(callee)

        elif node.type == "go_statement":
            # go someFunc()  or  go obj.Method()
            # The first child after "go" is the call_expression
            for child in node.children:
                if child.type == "call_expression":
                    fn = child.child_by_field_name("function")
                    if fn:
                        callee = self._resolve_callee(fn, source)
                        if callee and callee not in _GO_BUILTIN_SKIP:
                            callees.add(callee)

        # Recurse — but DON'T recurse into nested function literals to avoid
        # attributing closure calls to the outer function (they get their own entry)
        for child in node.children:
            if child.type != "func_literal":
                self._walk_calls(child, callees, source)

    def _resolve_callee(self, fn_node, source: bytes) -> Optional[str]:
        """Resolve a call target to a function name matching the graph's naming.

        Returns:
          - "InitLogger"              for plain function calls
          - "Server.ListenAndServe"   for method calls (receiver-qualified)
          - None                      for stdlib/unresolvable calls
        """
        if fn_node.type == "identifier":
            # Direct call: InitLogger()
            name = fn_node.text.decode("utf-8")
            return name

        if fn_node.type == "selector_expression":
            # Method call: s.handleAuth() or pkg.Function()
            operand = fn_node.child_by_field_name("operand")
            field = fn_node.child_by_field_name("field")
            if not field:
                return None

            method_name = field.text.decode("utf-8")

            if operand:
                operand_text = operand.text.decode("utf-8")
                # Skip known stdlib packages (fmt.Sprintf, http.Error, etc.)
                if operand_text in _GO_STDLIB_SKIP:
                    return None

                # Check if the operand looks like a package (starts with lowercase)
                # vs a variable/receiver (could be either case, but we try both)
                # Return just the method name — the graph resolver will match
                # against both "Method" and "Type.Method" forms
                return method_name

        return None

    def _extract_receiver_type(self, receiver_node) -> Optional[str]:
        """Extract the receiver type from a method_declaration's receiver.

        (s *Server) → "Server"
        (c Client)  → "Client"
        """
        if not receiver_node:
            return None
        for child in receiver_node.children:
            if child.type == "parameter_declaration":
                type_node = child.child_by_field_name("type")
                if type_node:
                    # Strip pointer: *Server → Server
                    return type_node.text.decode("utf-8").lstrip("*")
        return None


# ── Python builtins to skip ───────────────────────────────────────────────────

_PYTHON_BUILTIN_SKIP = frozenset({
    "print", "len", "range", "enumerate", "zip", "map", "filter",
    "str", "int", "float", "bool", "list", "dict", "set", "tuple",
    "isinstance", "issubclass", "hasattr", "getattr", "setattr",
    "type", "super", "property", "staticmethod", "classmethod",
    "open", "sorted", "reversed", "min", "max", "sum", "abs",
    "any", "all", "next", "iter", "id", "hash", "repr", "format",
    # Log methods themselves — we don't want edges to logger calls
    "debug", "info", "warning", "error", "critical", "exception",
    "fatal", "log",
})
