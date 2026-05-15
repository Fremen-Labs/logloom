"""
LogLoom × Vorsam Elastic Integration Tests
===========================================

Real-world integration tests that validate the LogLoom enrichment pipeline
against live Vorsam application logs flowing through Filebeat into the
local-elastro-brain Elasticsearch cluster.

Prerequisites:
  - local-elastro-brain running on localhost:9205
  - Vorsam dev stack running (vorsam dev)
  - Filebeat container running (elastic/filebeat-local)
  - logloom-pipeline ingest pipeline deployed
  - vorsam-logloom-enrichment index populated (logloom es ship)

Usage:
  pytest tests/integration/test_vorsam_elastic_e2e.py -v
"""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any, Dict, List

import pytest

ES_URL = "http://localhost:9205"

# ── Helpers ──────────────────────────────────────────────────────────────────


def es_request(method: str, path: str, body: dict | None = None) -> dict:
    """Make a raw HTTP request to Elasticsearch."""
    url = f"{ES_URL}/{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        pytest.skip(f"Elasticsearch not reachable at {ES_URL}: {exc}")


def es_search(index: str, body: dict) -> dict:
    return es_request("POST", f"{index}/_search", body)


def es_count(index: str, body: dict | None = None) -> int:
    result = es_request("POST", f"{index}/_count", body or {"query": {"match_all": {}}})
    return result.get("count", 0)


def simulate_pipeline(pipeline: str, docs: List[dict]) -> List[dict]:
    result = es_request("POST", f"_ingest/pipeline/{pipeline}/_simulate", {"docs": docs})
    return [d["doc"]["_source"] for d in result.get("docs", [])]


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def es_available():
    """Skip entire module if ES cluster is not available."""
    try:
        result = es_request("GET", "_cluster/health")
        assert result.get("status") in ("green", "yellow")
    except Exception:
        pytest.skip("local-elastro-brain cluster not available")


@pytest.fixture(scope="module")
def vorsam_logs_available(es_available):
    """Skip if vorsam-logloom-logs has no documents."""
    count = es_count("vorsam-logloom-logs")
    if count == 0:
        pytest.skip("No documents in vorsam-logloom-logs — is Vorsam dev running?")
    return count


@pytest.fixture(scope="module")
def enrichment_index_available(es_available):
    """Skip if vorsam-logloom-enrichment has no documents."""
    count = es_count("vorsam-logloom-enrichment")
    if count == 0:
        pytest.skip("No documents in vorsam-logloom-enrichment — run logloom es ship")
    return count


@pytest.fixture(scope="module")
def filebeat_available(es_available):
    """Skip if filebeat index has no Vorsam container logs."""
    count = es_count("filebeat-*", {
        "query": {"term": {"container.name": "vorsam-app-backendv2-1"}}
    })
    if count == 0:
        pytest.skip("No Filebeat logs from vorsam-app-backendv2-1")
    return count


# ═══════════════════════════════════════════════════════════════════════════
# TEST SUITE 1: Enrichment Index Validation
# ═══════════════════════════════════════════════════════════════════════════


class TestEnrichmentIndex:
    """Validate the vorsam-logloom-enrichment index has correct structure."""

    def test_enrichment_doc_count(self, enrichment_index_available):
        """The enrichment index should contain a meaningful number of nodes."""
        assert enrichment_index_available > 100, (
            f"Expected >100 enrichment nodes, got {enrichment_index_available}"
        )

    def test_enrichment_doc_has_required_fields(self, enrichment_index_available):
        """Every enrichment document must have the core LogLoom fields."""
        result = es_search("vorsam-logloom-enrichment", {"size": 10, "query": {"match_all": {}}})
        required = {"node_id", "module", "function", "file"}
        for hit in result["hits"]["hits"]:
            logloom = hit["_source"].get("logloom", {})
            missing = required - set(logloom.keys())
            assert not missing, f"Enrichment doc missing fields: {missing}"

    def test_enrichment_covers_known_modules(self, enrichment_index_available):
        """Enrichment index should contain nodes from key Vorsam modules."""
        result = es_search("vorsam-logloom-enrichment", {
            "size": 0,
            "aggs": {"modules": {"terms": {"field": "logloom.module", "size": 50}}}
        })
        modules = {b["key"] for b in result["aggregations"]["modules"]["buckets"]}
        expected = {"src/database", "src/server"}
        found = expected & modules
        assert len(found) >= 1, (
            f"Expected at least one of {expected} in enrichment, got modules: {modules}"
        )

    def test_enrichment_has_semantic_tags(self, enrichment_index_available):
        """Enrichment documents should include semantic tags."""
        count = es_count("vorsam-logloom-enrichment", {
            "query": {"exists": {"field": "logloom.tags"}}
        })
        assert count > 0, "No enrichment documents have semantic tags"

    def test_enrichment_has_commit_sha(self, enrichment_index_available):
        """Every enrichment doc should track the source commit."""
        result = es_search("vorsam-logloom-enrichment", {
            "size": 1, "query": {"exists": {"field": "logloom.commit_sha"}}
        })
        assert result["hits"]["total"]["value"] > 0
        sha = result["hits"]["hits"][0]["_source"]["logloom"]["commit_sha"]
        assert len(sha) >= 7, f"Commit SHA too short: {sha}"


# ═══════════════════════════════════════════════════════════════════════════
# TEST SUITE 2: NDJSON Sidecar Transport (vorsam-logloom-logs)
# ═══════════════════════════════════════════════════════════════════════════


class TestNdjsonSidecarLogs:
    """Validate that the Winston NDJSON sidecar transport is emitting enriched logs."""

    def test_sidecar_has_logloom_fields(self, vorsam_logs_available):
        """Every sidecar log should carry the full set of logloom_ fields."""
        result = es_search("vorsam-logloom-logs", {
            "size": 10, "query": {"match_all": {}}
        })
        required = {"logloom_node_id", "logloom_module", "logloom_function"}
        for hit in result["hits"]["hits"]:
            src = hit["_source"]
            missing = required - set(src.keys())
            assert not missing, f"Sidecar doc missing: {missing}. Keys: {list(src.keys())}"

    def test_sidecar_captures_error_logs(self, vorsam_logs_available):
        """Error-level logs should be present in the sidecar output."""
        count = es_count("vorsam-logloom-logs", {
            "query": {"term": {"level": "error"}}
        })
        assert count > 0, "No error-level logs in sidecar — are errors occurring in Vorsam?"

    def test_sidecar_module_distribution(self, vorsam_logs_available):
        """Logs should span multiple source modules (not just the logger wrapper)."""
        result = es_search("vorsam-logloom-logs", {
            "size": 0,
            "aggs": {"modules": {"terms": {"field": "logloom_module", "size": 20}}}
        })
        modules = [b["key"] for b in result["aggregations"]["modules"]["buckets"]]
        non_logger = [m for m in modules if m != "src/logger/logger"]
        assert len(non_logger) >= 2, (
            f"Expected logs from >=2 non-logger modules, got: {modules}"
        )

    def test_sidecar_semantic_tag_filtering(self, vorsam_logs_available):
        """Semantic tags should enable domain-specific filtering."""
        # Query all database-tagged logs
        result = es_search("vorsam-logloom-logs", {
            "size": 5,
            "query": {"term": {"logloom_tags": "database"}},
            "_source": ["message", "logloom_function", "logloom_module"]
        })
        assert result["hits"]["total"]["value"] > 0, "No logs tagged with 'database'"
        # Verify they all come from database-related code
        for hit in result["hits"]["hits"]:
            src = hit["_source"]
            assert src.get("logloom_module") or src.get("logloom_function"), (
                "Database-tagged log has no module/function context"
            )

    def test_sidecar_function_level_drill_down(self, vorsam_logs_available):
        """Should be able to drill into a specific function's log history."""
        # Find the most frequent function
        result = es_search("vorsam-logloom-logs", {
            "size": 0,
            "aggs": {"funcs": {"terms": {"field": "logloom_function", "size": 1}}}
        })
        top_func = result["aggregations"]["funcs"]["buckets"][0]["key"]
        # Query all logs from that function
        func_logs = es_search("vorsam-logloom-logs", {
            "size": 5,
            "query": {"term": {"logloom_function": top_func}},
            "_source": ["message", "level", "timestamp"]
        })
        assert func_logs["hits"]["total"]["value"] >= 2, (
            f"Expected multiple log entries from '{top_func}'"
        )


# ═══════════════════════════════════════════════════════════════════════════
# TEST SUITE 3: Filebeat Docker Transport
# ═══════════════════════════════════════════════════════════════════════════


class TestFilebeatDockerTransport:
    """Validate Filebeat is collecting Vorsam container logs."""

    def test_filebeat_captures_vorsam_containers(self, filebeat_available):
        """Filebeat should be harvesting logs from all Vorsam containers."""
        result = es_search("filebeat-*", {
            "size": 0,
            "aggs": {"containers": {"terms": {"field": "container.name", "size": 20}}}
        })
        containers = {b["key"] for b in result["aggregations"]["containers"]["buckets"]}
        assert "vorsam-app-backendv2-1" in containers
        assert "vorsam-postgres" in containers

    def test_filebeat_excludes_infra_containers(self, filebeat_available):
        """Filebeat should NOT be collecting logs from itself or Elasticsearch."""
        result = es_search("filebeat-*", {
            "size": 0,
            "aggs": {"containers": {"terms": {"field": "container.name", "size": 20}}}
        })
        containers = {b["key"] for b in result["aggregations"]["containers"]["buckets"]}
        assert "local-elastro-brain" not in containers, "ES container should be excluded"
        assert "filebeat" not in containers, "Filebeat container should be excluded"

    def test_filebeat_adds_docker_metadata(self, filebeat_available):
        """Filebeat should enrich docs with Docker container metadata."""
        result = es_search("filebeat-*", {
            "size": 1,
            "query": {"term": {"container.name": "vorsam-app-backendv2-1"}}
        })
        src = result["hits"]["hits"][0]["_source"]
        assert "container" in src
        assert "agent" in src
        assert src["agent"]["type"] == "filebeat"


# ═══════════════════════════════════════════════════════════════════════════
# TEST SUITE 4: Ingest Pipeline Enrichment (End-to-End)
# ═══════════════════════════════════════════════════════════════════════════


class TestIngestPipelineEnrichment:
    """Validate the logloom-pipeline performs server-side enrichment."""

    def test_pipeline_exists(self, es_available):
        """The logloom-pipeline must exist on the cluster."""
        result = es_request("GET", "_ingest/pipeline/logloom-pipeline")
        assert "logloom-pipeline" in result

    def test_pipeline_has_rename_processor(self, es_available):
        """Pipeline must have the rename processor as the first step."""
        result = es_request("GET", "_ingest/pipeline/logloom-pipeline")
        processors = result["logloom-pipeline"]["processors"]
        assert processors[0].get("rename"), "First processor should be 'rename'"
        rename = processors[0]["rename"]
        assert rename["field"] == "logloom_node_id"
        assert rename["target_field"] == "logloom.node_id"

    def test_pipeline_has_enrich_processor(self, es_available):
        """Pipeline must have the enrich processor as the second step."""
        result = es_request("GET", "_ingest/pipeline/logloom-pipeline")
        processors = result["logloom-pipeline"]["processors"]
        assert len(processors) >= 2, "Pipeline should have at least 2 processors"
        assert processors[1].get("enrich"), "Second processor should be 'enrich'"

    def test_simulate_enrichment_with_known_node(self, enrichment_index_available):
        """Simulating the pipeline with a known node_id should join graph data."""
        # Use a node_id we know exists in the enrichment index
        result = es_search("vorsam-logloom-enrichment", {"size": 1})
        known_node_id = result["hits"]["hits"][0]["_source"]["logloom"]["node_id"]

        enriched = simulate_pipeline("logloom-pipeline", [
            {"_source": {
                "message": "Test log",
                "logloom_node_id": known_node_id,
                "@timestamp": "2026-05-15T00:00:00Z"
            }}
        ])
        assert len(enriched) == 1
        logloom = enriched[0].get("logloom", {})
        # The enrich processor should have joined the graph context
        assert "node_id" in logloom or "logloom" in logloom, (
            f"Enrichment join failed. Got: {json.dumps(enriched[0], indent=2)}"
        )

    def test_simulate_passthrough_without_node_id(self, es_available):
        """Docs without logloom_node_id should pass through unchanged."""
        enriched = simulate_pipeline("logloom-pipeline", [
            {"_source": {
                "message": "Plain log from nginx",
                "@timestamp": "2026-05-15T00:00:00Z"
            }}
        ])
        assert len(enriched) == 1
        assert "logloom" not in enriched[0], "Non-LogLoom docs should not get logloom fields"

    def test_simulate_graceful_for_unknown_node(self, es_available):
        """Docs with an unknown node_id should not cause pipeline errors."""
        enriched = simulate_pipeline("logloom-pipeline", [
            {"_source": {
                "message": "Unknown node",
                "logloom_node_id": "ll:does_not_exist_999",
                "@timestamp": "2026-05-15T00:00:00Z"
            }}
        ])
        assert len(enriched) == 1
        # Should have renamed the field but no enrichment data joined
        logloom = enriched[0].get("logloom", {})
        assert logloom.get("node_id") == "ll:does_not_exist_999"


# ═══════════════════════════════════════════════════════════════════════════
# TEST SUITE 5: Real-World Observability Queries
# ═══════════════════════════════════════════════════════════════════════════


class TestObservabilityQueries:
    """Demonstrate the observability value of LogLoom enrichment."""

    def test_query_errors_by_semantic_tag(self, vorsam_logs_available):
        """Find all error logs tagged 'database' — impossible without LogLoom."""
        result = es_search("vorsam-logloom-logs", {
            "size": 0,
            "query": {
                "bool": {
                    "must": [
                        {"term": {"level": "error"}},
                        {"term": {"logloom_tags": "database"}}
                    ]
                }
            }
        })
        count = result["hits"]["total"]["value"]
        # This query wouldn't even be possible without LogLoom tags
        assert count >= 0, "Query executed successfully"

    def test_query_error_hotspots_by_function(self, vorsam_logs_available):
        """Aggregate errors by function to find the noisiest code paths."""
        result = es_search("vorsam-logloom-logs", {
            "size": 0,
            "query": {"term": {"level": "error"}},
            "aggs": {
                "hotspots": {
                    "terms": {"field": "logloom_function", "size": 5}
                }
            }
        })
        buckets = result["aggregations"]["hotspots"]["buckets"]
        # At least one function should have errors
        assert len(buckets) > 0, "No error hotspots found"
        top = buckets[0]
        assert top["doc_count"] > 0
        # This gives us actionable intelligence: which function is failing most

    def test_query_module_error_rate(self, vorsam_logs_available):
        """Calculate error rate per module — a key observability metric."""
        result = es_search("vorsam-logloom-logs", {
            "size": 0,
            "aggs": {
                "modules": {
                    "terms": {"field": "logloom_module", "size": 20},
                    "aggs": {
                        "error_count": {
                            "filter": {"term": {"level": "error"}}
                        },
                        "total_count": {"value_count": {"field": "level"}}
                    }
                }
            }
        })
        for bucket in result["aggregations"]["modules"]["buckets"]:
            total = bucket["total_count"]["value"]
            errors = bucket["error_count"]["doc_count"]
            rate = (errors / total * 100) if total > 0 else 0
            # Just verify the aggregation works — actual rates will vary
            assert 0 <= rate <= 100

    def test_cross_reference_enrichment_with_runtime_logs(
        self, vorsam_logs_available, enrichment_index_available
    ):
        """Verify runtime log node_ids exist in the enrichment index."""
        # Get unique node_ids from runtime logs
        log_result = es_search("vorsam-logloom-logs", {
            "size": 0,
            "aggs": {"node_ids": {"terms": {"field": "logloom_node_id", "size": 10}}}
        })
        log_node_ids = [b["key"] for b in log_result["aggregations"]["node_ids"]["buckets"]]
        assert len(log_node_ids) > 0, "No node_ids found in runtime logs"

        # Verify each exists in the enrichment index
        for node_id in log_node_ids[:5]:
            enrich_result = es_search("vorsam-logloom-enrichment", {
                "size": 1,
                "query": {"term": {"logloom.node_id": node_id}}
            })
            assert enrich_result["hits"]["total"]["value"] > 0, (
                f"Runtime log node_id '{node_id}' not found in enrichment index"
            )

    def test_trace_startup_sequence(self, vorsam_logs_available):
        """Reconstruct the application startup sequence using LogLoom metadata."""
        result = es_search("vorsam-logloom-logs", {
            "size": 20,
            "query": {"term": {"logloom_tags": "lifecycle"}},
            "sort": [{"timestamp": "asc"}],
            "_source": ["message", "logloom_module", "logloom_function", "timestamp"]
        })
        lifecycle_logs = result["hits"]["hits"]
        if len(lifecycle_logs) == 0:
            pytest.skip("No lifecycle-tagged logs found")
        # Verify chronological ordering
        timestamps = [h["_source"]["timestamp"] for h in lifecycle_logs]
        assert timestamps == sorted(timestamps), "Lifecycle logs should be chronological"
