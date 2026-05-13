"""Tests for Issue #19 — Graph diff."""

from logloom.graph.model import LogLoomGraph, GraphNode
from logloom.intelligence.diff import diff_graphs


def _make_graph(nodes_data, built_at="2026-01-01T00:00:00"):
    nodes = {}
    for data in nodes_data:
        nid = data["node_id"]
        nodes[nid] = GraphNode(
            node_id=nid,
            file=data.get("file", "test.py"),
            module=data.get("module", "app"),
            function=data.get("function", "func"),
            level=data.get("level", "info"),
            message_template=data.get("message_template", "msg"),
            line=data.get("line", 1),
            semantic_tags=data.get("semantic_tags", []),
        )
    return LogLoomGraph(project="test", built_at=built_at, nodes=nodes)


def test_diff_no_changes():
    g = _make_graph([{"node_id": "ll:aaa", "message_template": "hello"}])
    result = diff_graphs(g, g)
    assert not result.has_changes
    assert result.summary() == "No changes"


def test_diff_added():
    old = _make_graph([])
    new = _make_graph([{"node_id": "ll:aaa", "message_template": "new msg"}])
    result = diff_graphs(old, new)

    assert len(result.added) == 1
    assert result.added[0].node_id == "ll:aaa"
    assert not result.removed


def test_diff_removed():
    old = _make_graph([{"node_id": "ll:aaa", "message_template": "old msg"}])
    new = _make_graph([])
    result = diff_graphs(old, new)

    assert len(result.removed) == 1
    assert not result.added


def test_diff_moved():
    old = _make_graph([{"node_id": "ll:aaa", "file": "a.py", "line": 10}])
    new = _make_graph([{"node_id": "ll:aaa", "file": "b.py", "line": 20}])
    result = diff_graphs(old, new)

    assert len(result.moved) == 1
    assert "a.py:10" in result.moved[0].details
    assert "b.py:20" in result.moved[0].details


def test_diff_modified():
    old = _make_graph([{"node_id": "ll:aaa", "message_template": "old msg", "level": "info"}])
    new = _make_graph([{"node_id": "ll:aaa", "message_template": "new msg", "level": "error"}])
    result = diff_graphs(old, new)

    assert len(result.modified) == 1
    assert "message:" in result.modified[0].details
    assert "level:" in result.modified[0].details


def test_diff_summary():
    old = _make_graph([
        {"node_id": "ll:aaa"},
        {"node_id": "ll:bbb"},
    ])
    new = _make_graph([
        {"node_id": "ll:bbb"},
        {"node_id": "ll:ccc"},
    ])
    result = diff_graphs(old, new)

    assert "+1 added" in result.summary()
    assert "-1 removed" in result.summary()
    assert result.total_changes == 2
