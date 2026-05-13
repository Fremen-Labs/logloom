"""Tests for Issue #20 — Elasticsearch mapping generator."""

import json
from logloom.elasticsearch.mapping import (
    generate_component_template,
    generate_index_template,
    generate_enrichment_documents,
    render_mapping_json,
    LOGLOOM_FIELD_MAPPING,
)
from logloom.graph.model import LogLoomGraph, GraphNode


def _make_graph():
    return LogLoomGraph(
        project="test",
        built_at="2026-05-13T00:00:00",
        commit_sha="abc123",
        branch="main",
        nodes={
            "ll:aaa": GraphNode(
                node_id="ll:aaa",
                file="app.py",
                module="app",
                function="login",
                level="info",
                message_template="User login",
                line=10,
                semantic_tags=["auth"],
                call_parents=["ll:bbb"],
            ),
            "ll:bbb": GraphNode(
                node_id="ll:bbb",
                file="app.py",
                module="app",
                function="handler",
                level="error",
                message_template="Request failed",
                line=20,
                semantic_tags=["http", "error"],
                call_children=["ll:aaa"],
            ),
        },
    )


def test_component_template_structure():
    template = generate_component_template()
    assert "template" in template
    assert "mappings" in template["template"]
    assert "logloom" in template["template"]["mappings"]["properties"]

    props = template["template"]["mappings"]["properties"]["logloom"]["properties"]
    assert props["node_id"]["type"] == "keyword"
    assert props["tags"]["type"] == "keyword"
    assert props["message_template"]["type"] == "keyword"
    assert props["message_template"]["fields"]["text"]["type"] == "text"


def test_index_template_structure():
    template = generate_index_template(
        template_name="test",
        index_patterns=["test-*"],
        ilm_policy="hot-warm-delete",
    )
    assert template["index_patterns"] == ["test-*"]
    assert template["template"]["settings"]["index.lifecycle.name"] == "hot-warm-delete"
    assert "@timestamp" in template["template"]["mappings"]["properties"]
    assert "logloom" in template["template"]["mappings"]["properties"]


def test_enrichment_documents():
    graph = _make_graph()
    docs = generate_enrichment_documents(graph)
    assert len(docs) == 2

    doc_by_id = {d["_id"]: d for d in docs}
    aaa = doc_by_id["ll:aaa"]
    assert aaa["logloom"]["module"] == "app"
    assert aaa["logloom"]["tags"] == ["auth"]
    assert aaa["logloom"]["call_parents"] == ["ll:bbb"]
    assert aaa["logloom"]["commit_sha"] == "abc123"

    bbb = doc_by_id["ll:bbb"]
    assert bbb["logloom"]["call_children"] == ["ll:aaa"]


def test_render_mapping_json():
    result = render_mapping_json("component")
    parsed = json.loads(result)
    assert "template" in parsed

    result = render_mapping_json("index", template_name="logs")
    parsed = json.loads(result)
    assert "index_patterns" in parsed
