"""Tests for Issue #14 — Semantic tag auto-inference."""

from logloom.graph.model import LogLoomGraph, GraphNode
from logloom.intelligence.tagger import infer_tags


def _make_graph(nodes_data):
    """Helper to build a graph from a list of dicts."""
    nodes = {}
    for i, data in enumerate(nodes_data):
        node_id = data.get("node_id", f"ll:test{i:08d}")
        nodes[node_id] = GraphNode(
            node_id=node_id,
            file=data.get("file", "test.py"),
            module=data.get("module", "app.test"),
            function=data.get("function", "test_func"),
            level=data.get("level", "info"),
            message_template=data.get("message_template", "test message"),
            line=data.get("line", i + 1),
            semantic_tags=data.get("semantic_tags", []),
            lexical_parents=data.get("lexical_parents", []),
        )
    return LogLoomGraph(project="test", built_at="2026", nodes=nodes)


def test_tags_from_function_name():
    graph = _make_graph([
        {"function": "authenticate_user", "message_template": "Starting"},
        {"function": "process_payment", "message_template": "Charging"},
        {"function": "retry_connection", "message_template": "Trying"},
    ])
    result = infer_tags(graph)
    nodes = list(result.nodes.values())

    assert "auth" in nodes[0].semantic_tags
    assert "payment" in nodes[1].semantic_tags
    assert "retry" in nodes[2].semantic_tags


def test_tags_from_module_path():
    graph = _make_graph([
        {"module": "app.auth.service", "message_template": "hello"},
        {"module": "app.db.repository", "message_template": "querying"},
    ])
    result = infer_tags(graph)
    nodes = list(result.nodes.values())

    assert "auth" in nodes[0].semantic_tags
    assert "database" in nodes[1].semantic_tags


def test_tags_from_message_content():
    graph = _make_graph([
        {"message_template": "User login successful"},
        {"message_template": "Request timeout after 30s"},
        {"message_template": "Payment charge completed"},
    ])
    result = infer_tags(graph)
    nodes = list(result.nodes.values())

    assert "auth" in nodes[0].semantic_tags
    assert "performance" in nodes[1].semantic_tags
    assert "payment" in nodes[2].semantic_tags


def test_tags_from_level():
    graph = _make_graph([
        {"level": "error", "message_template": "Something broke"},
        {"level": "debug", "message_template": "Trace data"},
        {"level": "warning", "message_template": "Deprecation notice"},
    ])
    result = infer_tags(graph)
    nodes = list(result.nodes.values())

    assert "error" in nodes[0].semantic_tags
    assert "debug" in nodes[1].semantic_tags
    assert "warning" in nodes[2].semantic_tags


def test_existing_tags_preserved():
    """Manual tags should not be lost by the auto-inference pass."""
    graph = _make_graph([
        {"semantic_tags": ["custom-tag"], "function": "login", "message_template": "hi"},
    ])
    result = infer_tags(graph)
    node = list(result.nodes.values())[0]

    assert "custom-tag" in node.semantic_tags
    assert "auth" in node.semantic_tags  # inferred from function name


def test_infer_tags_is_pure():
    """infer_tags should return a new graph, not mutate the original."""
    graph = _make_graph([
        {"function": "login", "message_template": "test"},
    ])
    original_tags = list(graph.nodes.values())[0].semantic_tags.copy()
    result = infer_tags(graph)

    # Original should be unchanged
    assert list(graph.nodes.values())[0].semantic_tags == original_tags
    # Result should have new tags
    assert "auth" in list(result.nodes.values())[0].semantic_tags
