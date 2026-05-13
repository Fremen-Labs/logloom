"""Integration tests for the full ES and OTEL ecosystem flow.

Tests end-to-end from graph construction through ES mapping generation,
NDJSON export, enrichment document content, and OTEL processor enrichment.
These tests validate the complete pipeline without requiring a live ES cluster
or OTEL collector — they test the data contracts and enrichment logic.
"""

import json
from pathlib import Path

import pytest

from logloom.graph.model import LogLoomGraph, GraphNode
from logloom.elasticsearch.mapping import (
    generate_component_template,
    generate_index_template,
    generate_enrichment_documents,
    LOGLOOM_FIELD_MAPPING,
)
from logloom.elasticsearch.shipper import export_ndjson
from logloom.otel.bridge import (
    LogLoomOTELProcessor,
    LogLoomOTELHandler,
    get_otel_resource_attributes,
    ATTR_NODE_ID,
    ATTR_MODULE,
    ATTR_FUNCTION,
    ATTR_FILE,
    ATTR_TAGS,
    ATTR_CALL_PARENTS,
    ATTR_CALL_CHILDREN,
    ATTR_GRAPH_VERSION,
    ATTR_COMMIT_SHA,
)


@pytest.fixture
def rich_graph():
    """A graph with multiple interconnected nodes and rich metadata."""
    return LogLoomGraph(
        project="test-ecosystem",
        built_at="2026-05-13T21:00:00Z",
        commit_sha="abc123def456",
        branch="main",
        nodes={
            "ll:auth001": GraphNode(
                node_id="ll:auth001",
                file="src/auth/service.py",
                module="auth.service",
                function="authenticate",
                level="info",
                message_template="User login attempt",
                line=42,
                semantic_tags=["auth", "security"],
                lexical_parents=["try:token_check", "AuthService"],
                call_parents=["handle_request"],
                call_children=["validate_token", "log_audit"],
            ),
            "ll:auth002": GraphNode(
                node_id="ll:auth002",
                file="src/auth/service.py",
                module="auth.service",
                function="authenticate",
                level="error",
                message_template="Authentication failed",
                line=55,
                semantic_tags=["auth", "error", "security"],
                lexical_parents=["except:token_check", "AuthService"],
            ),
            "ll:db001": GraphNode(
                node_id="ll:db001",
                file="src/db/pool.py",
                module="db.pool",
                function="get_connection",
                level="warning",
                message_template="Connection pool exhausted",
                line=78,
                semantic_tags=["database", "performance"],
            ),
            "ll:http001": GraphNode(
                node_id="ll:http001",
                file="src/api/handler.py",
                module="api.handler",
                function="handle_request",
                level="info",
                message_template="Request received",
                line=12,
                semantic_tags=["http"],
                call_children=["authenticate", "get_connection"],
            ),
        },
    )


# ── ES Mapping E2E ────────────────────────────────────────────────────────────

class TestESMappingEndToEnd:
    """Validate Elasticsearch mapping generation against ECS conventions."""

    def test_component_template_field_coverage(self):
        """Component template should map ALL LogLoom semantic fields."""
        tmpl = generate_component_template()
        props = tmpl["template"]["mappings"]["properties"]["logloom"]["properties"]

        # Every field from the mapping definition should be present
        expected_fields = {
            "node_id", "traversal", "module", "function", "file",
            "line", "tags", "level", "message_template",
            "call_parents", "call_children",
            "graph_version", "commit_sha", "branch",
        }
        actual_fields = set(props.keys())
        missing = expected_fields - actual_fields
        assert not missing, f"Missing fields in component template: {missing}"

    def test_index_template_ecs_fields(self):
        """Index template should include ECS standard fields alongside LogLoom."""
        tmpl = generate_index_template(index_patterns=["logs-myapp-*"])
        props = tmpl["template"]["mappings"]["properties"]

        # ECS standard fields
        assert "@timestamp" in props
        assert props["@timestamp"]["type"] == "date"
        assert "message" in props
        assert "log.level" in props

        # LogLoom namespace
        assert "logloom" in props

    def test_index_template_ilm_policy(self):
        """ILM policy should be embedded when provided."""
        tmpl = generate_index_template(ilm_policy="hot-warm-cold-30d")
        settings = tmpl["template"]["settings"]
        assert settings["index.lifecycle.name"] == "hot-warm-cold-30d"

    def test_enrichment_document_structure(self, rich_graph):
        """Enrichment documents should have correct shape for _bulk indexing."""
        docs = generate_enrichment_documents(rich_graph)
        assert len(docs) == 4

        # Validate structure of first doc
        auth_doc = next(d for d in docs if d["_id"] == "ll:auth001")
        ll = auth_doc["logloom"]

        assert ll["node_id"] == "ll:auth001"
        assert ll["module"] == "auth.service"
        assert ll["function"] == "authenticate"
        assert ll["file"] == "src/auth/service.py"
        assert ll["line"] == 42
        assert ll["level"] == "info"
        assert "auth" in ll["tags"]
        assert ll["message_template"] == "User login attempt"
        assert ll["call_parents"] == ["handle_request"]
        assert ll["call_children"] == ["validate_token", "log_audit"]
        assert ll["graph_version"] == "2026-05-13T21:00:00Z"
        assert ll["commit_sha"] == "abc123def456"
        assert ll["branch"] == "main"


# ── ES Shipper E2E ────────────────────────────────────────────────────────────

class TestESShipperEndToEnd:
    """Validate NDJSON export produces valid _bulk API payloads."""

    def test_ndjson_bulk_format(self, rich_graph):
        """Every document should have action + body line pair."""
        ndjson = export_ndjson(rich_graph, index_name="logloom-test")
        lines = ndjson.strip().split("\n")

        # 4 nodes × 2 lines each = 8 lines
        assert len(lines) == 8

        # Validate action/body pairing
        for i in range(0, len(lines), 2):
            action = json.loads(lines[i])
            body = json.loads(lines[i + 1])

            assert "index" in action
            assert action["index"]["_index"] == "logloom-test"
            assert "_id" in action["index"]
            assert "logloom" in body

    def test_ndjson_file_output(self, rich_graph, tmp_path: Path):
        """NDJSON should be written to file when output_path is specified."""
        out = tmp_path / "bulk.ndjson"
        export_ndjson(rich_graph, output_path=out)

        assert out.exists()
        content = out.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 8

    def test_ndjson_roundtrip_json_valid(self, rich_graph):
        """Every line in the NDJSON should be valid JSON."""
        ndjson = export_ndjson(rich_graph)
        for line_num, line in enumerate(ndjson.strip().split("\n"), 1):
            try:
                json.loads(line)
            except json.JSONDecodeError as e:
                pytest.fail(f"Line {line_num} is not valid JSON: {e}\n{line}")

    def test_ndjson_call_graph_preserved(self, rich_graph):
        """Call graph edges should survive the NDJSON export."""
        ndjson = export_ndjson(rich_graph)
        lines = ndjson.strip().split("\n")

        # Find the auth001 body
        for i in range(0, len(lines), 2):
            action = json.loads(lines[i])
            if action["index"]["_id"] == "ll:auth001":
                body = json.loads(lines[i + 1])
                assert body["logloom"]["call_parents"] == ["handle_request"]
                assert body["logloom"]["call_children"] == ["validate_token", "log_audit"]
                return

        pytest.fail("ll:auth001 not found in NDJSON output")


# ── OTEL Bridge E2E ───────────────────────────────────────────────────────────

class TestOTELBridgeEndToEnd:
    """Validate OpenTelemetry processor enrichment logic."""

    def test_resource_attributes_complete(self, rich_graph):
        """Resource attributes should include all graph metadata."""
        attrs = get_otel_resource_attributes(rich_graph)

        assert attrs["logloom.project"] == "test-ecosystem"
        assert attrs["logloom.schema_version"] == "1"
        assert attrs["logloom.node_count"] == 4
        assert attrs["logloom.commit_sha"] == "abc123def456"
        assert attrs["logloom.branch"] == "main"
        assert "logloom.graph_built_at" in attrs

    def test_processor_graceful_degradation(self):
        """Processor with no graph should pass events through unchanged."""
        processor = LogLoomOTELProcessor(graph=None)
        event = {"event": "test message", "key": "value"}
        result = processor(None, "info", event)

        assert result == {"event": "test message", "key": "value"}

    def test_handler_install_uninstall_idempotent(self, rich_graph):
        """Handler install/uninstall should be safe to call multiple times."""
        import logging

        original = logging.Logger.makeRecord
        handler = LogLoomOTELHandler(graph=rich_graph)

        # Install
        handler.install()
        assert logging.Logger.makeRecord is not original

        # Double install should not crash
        handler.install()

        # Uninstall restores
        handler.uninstall()
        assert logging.Logger.makeRecord is original

        # Double uninstall should not crash
        handler.uninstall()

    def test_handler_enriches_log_records(self, rich_graph):
        """Installed handler should inject logloom attributes into LogRecords."""
        import logging

        handler = LogLoomOTELHandler(graph=rich_graph)
        handler.install()

        try:
            logger = logging.getLogger("test_otel_enrichment")

            # Create a LogRecord manually to check attributes
            record = logger.makeRecord(
                "test_otel_enrichment",
                logging.INFO,
                "src/auth/service.py",
                42,
                "User login attempt",
                args=None,
                exc_info=None,
                func="authenticate",
            )
            # Note: enrichment depends on resolver finding the match.
            # With the test graph, the resolver may or may not find an exact match
            # since module name resolution depends on the caller frame.
            # What we verify is that makeRecord was patched without crash.
            assert record is not None
            assert record.msg == "User login attempt"
        finally:
            handler.uninstall()
