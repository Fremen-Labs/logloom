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
from tree_sitter import Language, Parser, Query
try:
    from tree_sitter import QueryCursor
except ImportError:
    QueryCursor = None
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
        try:
            self.language = Language(tspython.language())
        except TypeError:
            self.language = Language(tspython.language(), "python")
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

        # Step 2: Identify which functions contain log sites (by qualified function name)
        # Maps qualified function name -> List[node_id]
        qualified_func_to_nodes: Dict[str, List[str]] = {}
        # Maps bare function name -> List[qualified_function_name]
        bare_func_to_qualified: Dict[str, List[str]] = {}

        for node in graph.nodes.values():
            qname = f"{node.module}.{node.function}" if node.module else node.function
            qualified_func_to_nodes.setdefault(qname, []).append(node.node_id)

            # Bare name is either the function name itself or the last component
            bare = node.function.rsplit(".", 1)[1] if "." in node.function else node.function
            bare_func_to_qualified.setdefault(bare, []).append(qname)

        # Set of all known modules in the graph
        known_modules = set(node.module for node in graph.nodes.values() if node.module)

        def _get_caller_module(caller_name: str) -> str:
            parts = caller_name.split(".")
            for i in range(len(parts), 0, -1):
                prefix = ".".join(parts[:i])
                if prefix in known_modules:
                    return prefix
            if "." in caller_name:
                return caller_name.rsplit(".", 1)[0]
            return ""

        def _resolve_callee_targets(caller_qname: str, callee: str) -> List[str]:
            """Resolve a callee name to its target qualified function names,
            preferring local/imported modules to prevent false positive matches.
            """
            caller_mod = _get_caller_module(caller_qname)

            # 1. Local module check
            if caller_mod:
                local_candidates = [
                    q for q in qualified_func_to_nodes
                    if q.startswith(f"{caller_mod}.") and (q.endswith(f".{callee}") or q.split(".")[-1] == callee)
                ]
                if local_candidates:
                    return local_candidates

            # 2. Imports graph check
            if caller_mod and graph.imports:
                imported_modules = graph.imports.get(caller_mod, [])
                import_candidates = []
                for imp in imported_modules:
                    # Resolve relative imports if needed
                    resolved_imp = imp
                    if imp.startswith("."):
                        dots = 0
                        while dots < len(imp) and imp[dots] == ".":
                            dots += 1
                        parent_parts = caller_mod.split(".")
                        if len(parent_parts) >= dots:
                            resolved_imp = ".".join(parent_parts[:-dots])
                            if imp[dots:]:
                                resolved_imp = f"{resolved_imp}.{imp[dots:]}"
                        else:
                            resolved_imp = imp.lstrip(".")

                    for q in qualified_func_to_nodes:
                        if q.startswith(f"{resolved_imp}.") and (q.endswith(f".{callee}") or q.split(".")[-1] == callee):
                            import_candidates.append(q)
                if import_candidates:
                    return import_candidates

            # 3. Global check (if there is a single unique match in the codebase)
            global_candidates = bare_func_to_qualified.get(callee, [])
            if not global_candidates and "." in callee:
                # E.g. MyClass.start
                bare_tail = callee.rsplit(".", 1)[1]
                global_candidates = bare_func_to_qualified.get(bare_tail, [])

            if len(global_candidates) == 1:
                return global_candidates
            elif len(global_candidates) > 1:
                # Multiple candidates found in different modules: avoid linking to prevent noise
                return []
            return []

        # Step 3: For each node, populate call_parents and call_children
        new_nodes: Dict[str, GraphNode] = {}
        for node_id, node in graph.nodes.items():
            parents: Set[str] = set()
            parent_names: Set[str] = set()
            children: Set[str] = set()
            child_names: Set[str] = set()

            q_node_func = f"{node.module}.{node.function}" if node.module else node.function

            # Find parent functions (functions that call this node's function)
            for caller_qname, callees in call_map.items():
                for callee in callees:
                    targets = _resolve_callee_targets(caller_qname, callee)
                    if q_node_func in targets and caller_qname != q_node_func:
                        # Find node IDs of caller
                        parent_node_ids = qualified_func_to_nodes.get(caller_qname, [])
                        for p_id in parent_node_ids:
                            parents.add(p_id)
                        # Track the caller's qualified name
                        parent_names.add(caller_qname)

            # Find child functions (functions called by this node's function)
            if q_node_func in call_map:
                for callee in call_map[q_node_func]:
                    targets = _resolve_callee_targets(q_node_func, callee)
                    for target_qname in targets:
                        if target_qname != q_node_func:
                            child_node_ids = qualified_func_to_nodes.get(target_qname, [])
                            for c_id in child_node_ids:
                                children.add(c_id)
                            child_names.add(target_qname)

            new_nodes[node_id] = node.model_copy(update={
                "call_parents": sorted(parents),
                "call_children": sorted(children),
                "call_parent_names": sorted(parent_names),
                "call_child_names": sorted(child_names),
            })

        return graph.model_copy(update={"nodes": new_nodes})

    def _scan_file(self, file_path: Path, call_map: Dict[str, Set[str]]):
        """Route a file to the correct language-specific scanner."""
        module_path = self._get_module_path(file_path)
        if file_path.suffix == ".py":
            self._extract_python_calls(file_path, module_path, call_map)
        elif file_path.suffix == ".go" and self._go_resolver:
            if not file_path.name.endswith("_test.go"):
                self._go_resolver.extract_calls(file_path, module_path, call_map)

    def _get_module_path(self, file_path: Path) -> str:
        if file_path.suffix == ".py":
            parts = list(file_path.with_suffix("").parts)
            if "src" in parts:
                idx = parts.index("src")
                return ".".join(parts[idx+1:])
            return ".".join(parts[-3:])
        elif file_path.suffix == ".go":
            return str(file_path.with_suffix(""))
        else:
            # TS/JS
            parts = list(file_path.with_suffix("").parts)
            for marker in ("src", "lib", "app", "pages", "components", "api"):
                if marker in parts:
                    idx = parts.index(marker)
                    return "/".join(parts[idx:])
            return "/".join(parts[-3:])

    # ── Python call extraction ────────────────────────────────────────────────

    def _extract_python_calls(self, file_path: Path, module_path: str, call_map: Dict[str, Set[str]]):
        """Parse a Python file and populate the call_map."""
        try:
            with open(file_path, "rb") as f:
                source = f.read()
        except (IOError, OSError):
            return

        tree = self.parser.parse(source)
        self._walk_python_functions(tree.root_node, module_path, call_map, source)

    def _walk_python_functions(self, node, module_path: str, call_map: Dict[str, Set[str]], source: bytes, class_stack: List[str] = None):
        """Recursively find function_definitions and extract calls from their bodies, preserving class context."""
        if class_stack is None:
            class_stack = []

        if node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                class_stack = class_stack + [name_node.text.decode("utf-8")]

        elif node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                func_name = name_node.text.decode("utf-8")
                if class_stack:
                    func_name = f"{'.'.join(class_stack)}.{func_name}"
                qualified_caller = f"{module_path}.{func_name}"
                body = node.child_by_field_name("body")
                if body:
                    callees = self._extract_python_callees(body, source)
                    existing = call_map.get(qualified_caller, set())
                    call_map[qualified_caller] = existing | callees

        for child in node.children:
            self._walk_python_functions(child, module_path, call_map, source, class_stack)

    def _extract_python_callees(self, body_node, source: bytes) -> Set[str]:
        """Use QueryCursor to find all function calls within a body node."""
        if QueryCursor is not None:
            cursor = QueryCursor(self._call_query)
            matches = cursor.matches(body_node)
        else:
            matches = self._call_query.matches(body_node)

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
        try:
            self.language = Language(tsgo.language())
        except TypeError:
            self.language = Language(tsgo.language(), "go")
        self.parser = Parser(self.language)

    def extract_calls(self, file_path: Path, module_path: str, call_map: Dict[str, Set[str]]):
        """Parse a Go file and populate call_map with caller→callee edges."""
        try:
            with open(file_path, "rb") as f:
                source = f.read()
        except (IOError, OSError):
            return

        tree = self.parser.parse(source)
        self._walk_go_declarations(tree.root_node, module_path, call_map, source)

    def _walk_go_declarations(self, node, module_path: str, call_map: Dict[str, Set[str]], source: bytes):
        """Find function/method declarations and package-level closures,
        extract call edges from their bodies."""
        if node.type == "function_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                func_name = name_node.text.decode("utf-8")
                qualified = f"{module_path}.{func_name}"
                body = node.child_by_field_name("body")
                if body:
                    callees = self._extract_go_callees(body, source)
                    existing = call_map.get(qualified, set())
                    call_map[qualified] = existing | callees

        elif node.type == "method_declaration":
            name_node = node.child_by_field_name("name")
            receiver = node.child_by_field_name("receiver")
            if name_node:
                method_name = name_node.text.decode("utf-8")
                # Qualify with receiver type: Server.handleAuth
                receiver_type = self._extract_receiver_type(receiver)
                if receiver_type:
                    qualified = f"{module_path}.{receiver_type}.{method_name}"
                else:
                    qualified = f"{module_path}.{method_name}"

                body = node.child_by_field_name("body")
                if body:
                    callees = self._extract_go_callees(body, source)
                    existing = call_map.get(qualified, set())
                    call_map[qualified] = existing | callees

        elif node.type == "var_declaration":
            # Package-level var declarations may contain Cobra command
            # structs with RunE/Run/PersistentPreRunE closures:
            #   var scanCmd = &cobra.Command{ RunE: func() { ... } }
            # Extract calls from any func_literals inside and attribute
            # them using the variable name as the caller key.
            self._extract_var_decl_closures(node, module_path, call_map, source)

        # Recurse into children (handles nested structures, init functions, etc.)
        for child in node.children:
            self._walk_go_declarations(child, module_path, call_map, source)

    def _extract_var_decl_closures(
        self, var_decl_node, module_path: str, call_map: Dict[str, Set[str]], source: bytes
    ):
        """Extract calls from func_literals inside package-level var declarations.

        Handles the Cobra pattern:
            var scanCmd = &cobra.Command{
                RunE: func(cmd *cobra.Command, args []string) error {
                    validateManifest("release.yaml")
                    ...
                },
            }

        The go_scanner assigns log calls inside these closures to '<module>'
        since there's no enclosing function_declaration. We use qualified '<module>' as
        the caller key so the call_graph resolver can match them.
        """
        func_literals = []
        self._find_func_literals(var_decl_node, func_literals)

        for fl in func_literals:
            body = fl.child_by_field_name("body")
            if body:
                callees = self._extract_go_callees(body, source)
                if callees:
                    # Use qualified '<module>' to match what go_scanner assigns
                    q_caller = f"{module_path}.<module>"
                    existing = call_map.get(q_caller, set())
                    call_map[q_caller] = existing | callees

    def _find_func_literals(self, node, results: list):
        """Recursively find all func_literal nodes within a subtree."""
        if node.type == "func_literal":
            results.append(node)
            return  # Don't recurse into nested func_literals
        for child in node.children:
            self._find_func_literals(child, results)

    def _extract_go_callees(self, body_node, source: bytes) -> Set[str]:
        """Walk a function body to find all call targets including goroutines.

        Handles:
          - Direct calls:    someFunc(args)             → "someFunc"
          - Method calls:    obj.Method(args)           → "Method"
          - Goroutine named: go serveControlPlane(ch)   → "serveControlPlane"
          - Goroutine method: go p.probeModel(ctx, fm)  → "probeModel"
          - Goroutine closure: go func() { calls... }() → walks closure body
          - Defer closure:   defer func() { calls }()   → walks closure body
          - Var-assigned closure: h := func(){ calls }  → walks closure body
          - Struct field closure: RunE: func(){ calls }  → walks closure body
        """
        callees: Set[str] = set()
        self._walk_calls(body_node, callees, source)
        return callees

    def _walk_calls(self, node, callees: Set[str], source: bytes):
        """Recursively walk the AST to find call targets."""
        if node.type == "call_expression":
            fn = node.child_by_field_name("function")
            if fn:
                # If the function is a func_literal being immediately invoked
                # (e.g. func(){ ... }()), walk the closure body.
                if fn.type == "func_literal":
                    closure_body = fn.child_by_field_name("body")
                    if closure_body:
                        self._walk_calls(closure_body, callees, source)
                else:
                    callee = self._resolve_callee(fn, source)
                    if callee and callee not in _GO_BUILTIN_SKIP:
                        callees.add(callee)

        elif node.type == "go_statement":
            # Goroutine launch — three patterns (A/B/C)
            self._walk_closure_or_call_statement(node, callees, source)
            return

        elif node.type == "defer_statement":
            # Defer launch — same three patterns as goroutine:
            #   defer namedFunc()          → direct edge
            #   defer obj.Method()         → method edge
            #   defer func() { body }()    → walk closure body
            self._walk_closure_or_call_statement(node, callees, source)
            return

        # Recurse into children.
        # For func_literals: walk into them if they are assigned to a variable
        # (short_var_declaration / assignment_statement) or used as a struct
        # field value (keyed_element / literal_value). These closures execute
        # in the enclosing function's scope and their calls should be edges.
        for child in node.children:
            if child.type == "func_literal":
                if self._is_inlinable_closure(child):
                    closure_body = child.child_by_field_name("body")
                    if closure_body:
                        self._walk_calls(closure_body, callees, source)
                # else: standalone func_literal that gets its own graph entry
            else:
                self._walk_calls(child, callees, source)

    def _walk_closure_or_call_statement(
        self, node, callees: Set[str], source: bytes
    ):
        """Handle go_statement and defer_statement uniformly.

        Both share three patterns:
          A: go/defer namedFunc(args)
          B: go/defer obj.Method(args)
          C: go/defer func() { body }()   → walk closure body
        """
        for child in node.children:
            if child.type == "call_expression":
                fn = child.child_by_field_name("function")
                if fn:
                    if fn.type == "func_literal":
                        closure_body = fn.child_by_field_name("body")
                        if closure_body:
                            self._walk_calls(closure_body, callees, source)
                    else:
                        callee = self._resolve_callee(fn, source)
                        if callee and callee not in _GO_BUILTIN_SKIP:
                            callees.add(callee)

    def _is_inlinable_closure(self, func_literal_node) -> bool:
        """Determine if a func_literal's calls should be inlined into the enclosing function.

        Returns True for closures that are:
          - Assigned to a variable:  handler := func() { ... }
          - Used as a struct field:  RunE: func(cmd, args) error { ... }
          - Passed as a callback argument: http.HandleFunc("/", func(w,r){ ... })

        Returns False for standalone closures that would get their own graph entry
        (this shouldn't happen in practice since standalone func_literals without
        context are rare).
        """
        # Walk up through intermediate AST wrapper nodes to find the
        # meaningful parent. In Go tree-sitter, func_literal's direct
        # parent is often an intermediate like expression_list or
        # literal_value, not the semantic parent we're looking for.
        #
        # Example AST chains:
        #   handler := func(){}   → func_literal → expression_list → short_var_declaration
        #   RunE: func(){}        → func_literal → keyed_element
        #   doWork(func(){})      → func_literal → argument_list
        #   var h = func(){}      → func_literal → expression_list → var_spec
        #   return func(){}       → func_literal → expression_list → return_statement
        _INTERMEDIATE_TYPES = frozenset({
            "expression_list", "literal_value", "parenthesized_expression",
        })

        current = func_literal_node.parent
        # Walk through up to 3 intermediate wrappers
        for _ in range(4):
            if current is None:
                return False

            if current.type in _INTERMEDIATE_TYPES:
                current = current.parent
                continue

            # Now `current` should be the semantic parent
            if current.type in (
                "short_var_declaration",
                "assignment_statement",
                "keyed_element",
                "argument_list",
                "var_spec",
                "return_statement",
                "var_declaration",
            ):
                return True

            # If we hit a statement or declaration we don't recognize,
            # it's not an inlinable closure
            return False

        return False


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

                # Return just the method name — the graph resolver will match
                # against both "Method" and "Type.Method" forms via the
                # bare_to_qualified index
                return method_name

        # Type assertion call: x.(Type).Method()
        # AST: selector_expression → type_assertion_expression → field_identifier
        if fn_node.type == "type_assertion_expression":
            # This is rare but can appear in chained patterns
            return None

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
