"""Issue #15 — Inter-function call-graph edge resolution.

Walks the AST of every Python file to build a mapping of which functions
call which other functions. Then resolves those edges against the set of
functions that contain log sites, populating `call_parents` and
`call_children` on the relevant GraphNodes.
"""

from __future__ import annotations

import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Query, QueryCursor
from pathlib import Path
from typing import Dict, List, Set, Tuple

from ..graph.model import GraphNode, LogLoomGraph

# ── Tree-sitter query for function calls ──────────────────────────────────────
# Captures:
#   @caller_func  — the enclosing function_definition
#   @callee       — the identifier of the called function

_CALL_GRAPH_QUERY = """
(function_definition
  name: (identifier) @caller_func
  body: (block
    (expression_statement
      (call
        function: [
          (identifier) @callee
          (attribute attribute: (identifier) @callee)
        ]
      )
    )
  )
)
"""

# A broader query that captures calls at any nesting depth within a function
_CALL_IN_FUNCTION_QUERY = """
(call
  function: [
    (identifier) @callee
    (attribute attribute: (identifier) @callee)
  ]
) @call_site
"""


class CallGraphResolver:
    """Builds inter-function call edges from source AST and maps them to graph nodes."""

    def __init__(self):
        self.language = Language(tspython.language())
        self.parser = Parser(self.language)
        self._call_query = Query(self.language, _CALL_IN_FUNCTION_QUERY)

    def resolve(
        self, graph: LogLoomGraph, source_paths: List[Path]
    ) -> LogLoomGraph:
        """Walk source files, build call edges, and enrich the graph.

        Returns a new graph with populated call_parents / call_children.
        """
        # Step 1: Build a mapping of function → set of callees across all files
        call_map: Dict[str, Set[str]] = {}  # caller_func → {callee_func, ...}
        for path in source_paths:
            if path.is_file() and path.suffix == ".py":
                self._extract_calls(path, call_map)
            elif path.is_dir():
                for py_file in path.rglob("*.py"):
                    self._extract_calls(py_file, call_map)

        # Step 2: Identify which functions contain log sites (by function name)
        func_to_nodes: Dict[str, List[str]] = {}  # function_name → [node_ids]
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
                    # This caller calls the function where our log site lives
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

    def _extract_calls(self, file_path: Path, call_map: Dict[str, Set[str]]):
        """Parse a file and populate the call_map with caller→callee edges."""
        with open(file_path, "rb") as f:
            source = f.read()

        tree = self.parser.parse(source)
        root = tree.root_node

        # Walk top-level and nested function definitions
        self._walk_functions(root, call_map, source)

    def _walk_functions(self, node, call_map: Dict[str, Set[str]], source: bytes):
        """Recursively find function_definitions and extract calls from their bodies."""
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                func_name = name_node.text.decode("utf-8")
                body = node.child_by_field_name("body")
                if body:
                    callees = self._extract_callees_from_body(body, source)
                    existing = call_map.get(func_name, set())
                    call_map[func_name] = existing | callees

        # Recurse into children (handles nested functions, classes, etc.)
        for child in node.children:
            self._walk_functions(child, call_map, source)

    def _extract_callees_from_body(self, body_node, source: bytes) -> Set[str]:
        """Use QueryCursor to find all function calls within a body node."""
        cursor = QueryCursor(self._call_query)
        matches = cursor.matches(body_node)

        callees: Set[str] = set()
        for _, captures in matches:
            callee_nodes = captures.get("callee", [])
            for callee_node in callee_nodes:
                callee_name = callee_node.text.decode("utf-8")
                # Skip common builtins that aren't meaningful edges
                if callee_name not in _BUILTIN_SKIP:
                    callees.add(callee_name)

        return callees


# Functions to skip when building call edges (builtins, common stdlib)
_BUILTIN_SKIP = frozenset({
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
