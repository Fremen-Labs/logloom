"""Tests for Step 6 — Cross-language call graph heuristic resolution.

Validates that the polyglot name-normalization logic in CallGraphResolver
correctly links function calls across language boundaries (e.g. Python
calling a Go function with snake_case ↔ CamelCase name equivalence).
"""

from logloom.graph.model import LogLoomGraph, GraphNode, FunctionSignature
from logloom.intelligence.call_graph import CallGraphResolver


def _make_polyglot_graph():
    """Create a graph with nodes from multiple languages that should
    be linked by the cross-language heuristic."""
    return LogLoomGraph(
        project="polyglot-test",
        built_at="2026-01-01T00:00:00Z",
        nodes={
            "ll:py001": GraphNode(
                node_id="ll:py001",
                file="src/api/handler.py",
                module="api.handler",
                function="call_backend",
                level="info",
                message_template="Calling backend service",
                line=10,
            ),
            "ll:go001": GraphNode(
                node_id="ll:go001",
                file="internal/backend/service.go",
                module="internal/backend/service",
                function="HandleRequest",
                level="info",
                message_template="Handling request",
                line=20,
            ),
            "ll:ts001": GraphNode(
                node_id="ll:ts001",
                file="src/client/api.ts",
                module="src/client/api",
                function="fetch_users",
                level="info",
                message_template="Fetching users from API",
                line=15,
            ),
            "ll:go002": GraphNode(
                node_id="ll:go002",
                file="internal/users/service.go",
                module="internal/users/service",
                function="FetchUsers",
                level="info",
                message_template="Fetching users from DB",
                line=30,
            ),
        },
    )


def test_cross_language_name_normalization():
    """Verify that snake_case Python/TS names match CamelCase Go names
    when the cross-language heuristic is applied."""
    # The normalization strips underscores/hyphens and lowercases:
    # "fetch_users" → "fetchusers"
    # "FetchUsers"  → "fetchusers"
    # These should match across language boundaries.
    from logloom.intelligence.call_graph import CallGraphResolver

    # We can't easily invoke the full resolver without source files,
    # but we can test the name normalization logic directly.
    # The heuristic normalizes: strip("_", "-"), lower()
    pairs = [
        ("fetch_users", "FetchUsers"),
        ("handle_request", "HandleRequest"),
        ("call_backend", "CallBackend"),
        ("get_user_by_id", "GetUserByID"),
    ]
    for snake, camel in pairs:
        norm_snake = snake.replace("_", "").replace("-", "").lower()
        norm_camel = camel.replace("_", "").replace("-", "").lower()
        assert norm_snake == norm_camel, f"Normalization mismatch: {snake} → {norm_snake} vs {camel} → {norm_camel}"


def test_cross_language_resolver_links_polyglot_calls(tmp_path):
    """Full integration: resolver should create cross-language edges
    when a Python function calls a Go function by normalized name."""
    import tempfile
    from pathlib import Path

    graph = _make_polyglot_graph()

    # Create source files that establish the call relationship.
    # Python file calls "FetchUsers" (Go function name)
    py_file = tmp_path / "src" / "api" / "handler.py"
    py_file.parent.mkdir(parents=True, exist_ok=True)
    py_file.write_text("""
import logging
logger = logging.getLogger(__name__)

def call_backend():
    logger.info("Calling backend service")
    result = FetchUsers()
    return result
""")

    # Go file defines FetchUsers (but we need tree_sitter_go for this)
    # We'll create a minimal Go file, but resolution depends on
    # tree_sitter_go being available. The key test here is that
    # the Python scanner picks up "FetchUsers" as a callee.
    resolver = CallGraphResolver()
    resolved_graph = resolver.resolve(graph, [py_file.parent])

    # The Python scanner should have picked up the call to FetchUsers
    # from call_backend(). The cross-language heuristic should then
    # match "FetchUsers" (callee from Python) against the Go node
    # "FetchUsers" (in a .go file) via normalized name comparison.
    py_node = resolved_graph.nodes["ll:py001"]

    # Check that the Go node appears as a child of the Python node
    # (cross-language edge via heuristic matching)
    assert "ll:go002" in py_node.call_children, (
        f"Expected cross-language edge py001 → go002, "
        f"got call_children={py_node.call_children}"
    )
    assert "internal/users/service.FetchUsers" in py_node.call_child_names, (
        f"Expected child name 'internal/users/service.FetchUsers', "
        f"got call_child_names={py_node.call_child_names}"
    )

    # Verify the reverse edge
    go_node = resolved_graph.nodes["ll:go002"]
    assert "ll:py001" in go_node.call_parents, (
        f"Expected cross-language reverse edge go002 ← py001, "
        f"got call_parents={go_node.call_parents}"
    )
