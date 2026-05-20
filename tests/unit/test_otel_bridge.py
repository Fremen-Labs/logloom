"""Tests for Issue #22 — OpenTelemetry Log Bridge."""

from logloom.otel.bridge import (
    LogLoomOTELProcessor,
    LogLoomOTELHandler,
    get_otel_resource_attributes,
    ATTR_NODE_ID,
    ATTR_MODULE,
    ATTR_TAGS,
)
from logloom.graph.model import LogLoomGraph, GraphNode


def _make_graph():
    return LogLoomGraph(
        project="test-otel",
        built_at="2026",
        commit_sha="def456",
        branch="main",
        nodes={
            "ll:aaa": GraphNode(
                node_id="ll:aaa", file="app.py", module="app",
                function="handle_request", level="info",
                message_template="Request received", line=10,
                semantic_tags=["http"],
                lexical_parents=["handle_request"],
            ),
        },
    )


def test_otel_resource_attributes():
    graph = _make_graph()
    attrs = get_otel_resource_attributes(graph)

    assert attrs["logloom.project"] == "test-otel"
    assert attrs["logloom.schema_version"] == "2.0"
    assert attrs["logloom.node_count"] == 1
    assert attrs["logloom.commit_sha"] == "def456"
    assert attrs["logloom.branch"] == "main"


def test_otel_processor_initialization():
    graph = _make_graph()
    processor = LogLoomOTELProcessor(graph=graph)
    assert processor._resolver is not None


def test_otel_processor_passthrough_without_graph():
    """Processor should pass events through unchanged when no graph is available."""
    processor = LogLoomOTELProcessor(graph=None)
    event_dict = {"event": "test message", "key": "value"}
    result = processor(None, "info", event_dict)
    assert result == {"event": "test message", "key": "value"}


def test_otel_handler_install_uninstall():
    """LogLoomOTELHandler should be installable and uninstallable without crashing."""
    import logging

    original_make_record = logging.Logger.makeRecord
    handler = LogLoomOTELHandler(graph=_make_graph())

    handler.install()
    assert logging.Logger.makeRecord is not original_make_record

    handler.uninstall()
    assert logging.Logger.makeRecord is original_make_record
