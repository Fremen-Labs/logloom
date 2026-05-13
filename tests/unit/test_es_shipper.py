"""Tests for Issue #21 — Elasticsearch NDJSON shipper."""

import json
from pathlib import Path
from logloom.elasticsearch.shipper import export_ndjson
from logloom.graph.model import LogLoomGraph, GraphNode


def _make_graph():
    return LogLoomGraph(
        project="test",
        built_at="2026",
        commit_sha="abc123",
        nodes={
            "ll:aaa": GraphNode(
                node_id="ll:aaa", file="a.py", module="app",
                function="f", level="info",
                message_template="hello", line=1,
                semantic_tags=["auth"],
            ),
            "ll:bbb": GraphNode(
                node_id="ll:bbb", file="b.py", module="app",
                function="g", level="error",
                message_template="fail", line=5,
            ),
        },
    )


def test_export_ndjson_format():
    graph = _make_graph()
    ndjson = export_ndjson(graph, index_name="test-index")

    lines = ndjson.strip().split("\n")
    # 2 docs = 4 lines (action + body per doc)
    assert len(lines) == 4

    # First line is an action
    action = json.loads(lines[0])
    assert action["index"]["_index"] == "test-index"
    assert action["index"]["_id"] in ("ll:aaa", "ll:bbb")

    # Second line is a body
    body = json.loads(lines[1])
    assert "logloom" in body


def test_export_ndjson_to_file(tmp_path: Path):
    graph = _make_graph()
    out = tmp_path / "export.ndjson"
    export_ndjson(graph, index_name="test-idx", output_path=out)

    assert out.exists()
    content = out.read_text()
    lines = content.strip().split("\n")
    assert len(lines) == 4
