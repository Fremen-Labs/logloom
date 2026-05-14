"""Tests for remediation fixes: auto-apply mapping, project name detection,
graph discovery, and enrichment pipeline generation."""

import json
import tempfile
from pathlib import Path

import pytest

from logloom.graph.model import LogLoomGraph, GraphNode
from logloom.graph.builder import _detect_project_name
from logloom.graph.store import _walk_up_for_graph, _discover_graph
from logloom.elasticsearch.shipper import export_ndjson, _generate_index_creation_body
from logloom.elasticsearch.mapping import (
    generate_enrich_policy,
    generate_enrich_pipeline,
)


@pytest.fixture
def simple_graph():
    return LogLoomGraph(
        project="test",
        built_at="2026-05-14T00:00:00Z",
        commit_sha="abc123",
        branch="main",
        nodes={
            "ll:001": GraphNode(
                node_id="ll:001",
                file="app.py",
                module="app",
                function="main",
                level="info",
                message_template="Starting up",
                line=1,
                semantic_tags=["lifecycle"],
            ),
        },
    )


class TestAutoApplyMapping:
    """Fix #2: export_ndjson should produce a sidecar mapping file."""

    def test_export_creates_mapping_sidecar(self, simple_graph, tmp_path):
        out = tmp_path / "enrichment.ndjson"
        export_ndjson(simple_graph, index_name="test-idx", output_path=out)

        mapping_path = tmp_path / "enrichment-mapping.json"
        assert mapping_path.exists(), "Sidecar mapping file was not created"

        body = json.loads(mapping_path.read_text())
        assert "mappings" in body
        props = body["mappings"]["properties"]["logloom"]["properties"]
        assert props["node_id"]["type"] == "keyword"
        assert props["tags"]["type"] == "keyword"
        assert props["line"]["type"] == "integer"

    def test_export_no_mapping_sidecar_when_disabled(self, simple_graph, tmp_path):
        out = tmp_path / "enrichment.ndjson"
        export_ndjson(simple_graph, index_name="test-idx", output_path=out,
                      include_mapping=False)

        mapping_path = tmp_path / "enrichment-mapping.json"
        assert not mapping_path.exists()

    def test_generate_index_creation_body(self):
        body = _generate_index_creation_body("my-index")
        assert body["settings"]["number_of_shards"] == 1
        logloom_props = body["mappings"]["properties"]["logloom"]["properties"]
        assert logloom_props["module"]["type"] == "keyword"


class TestProjectNameDetection:
    """Fix #4: auto-detect project name from pyproject.toml or directory name."""

    def test_pyproject_toml_detection(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "my-cool-app"\nversion = "1.0"\n')

        src = tmp_path / "src"
        src.mkdir()

        result = _detect_project_name([src])
        assert result == "my-cool-app"

    def test_setup_cfg_detection(self, tmp_path):
        setup_cfg = tmp_path / "setup.cfg"
        setup_cfg.write_text("[metadata]\nname = legacy-app\nversion = 2.0\n")

        src = tmp_path / "src"
        src.mkdir()

        result = _detect_project_name([src])
        assert result == "legacy-app"

    def test_fallback_to_directory_name(self, tmp_path):
        src = tmp_path / "awesome-project"
        src.mkdir()

        result = _detect_project_name([src])
        assert result == "awesome-project"


class TestGraphDiscovery:
    """Fix #3: LOGLOOM_GRAPH_PATH auto-discovery improvements."""

    def test_walk_up_finds_graph(self, tmp_path, simple_graph):
        # Create a graph file in the parent
        graph_file = tmp_path / "logloom-graph.json"
        graph_file.write_text(simple_graph.model_dump_json(indent=2))

        subdir = tmp_path / "src" / "app"
        subdir.mkdir(parents=True)

        found = _walk_up_for_graph(subdir)
        assert found is not None
        assert found == graph_file

    def test_walk_up_returns_none_when_missing(self, tmp_path):
        found = _walk_up_for_graph(tmp_path)
        assert found is None

    def test_walk_up_safety_limit(self, tmp_path):
        # Should not loop forever
        found = _walk_up_for_graph(Path("/"))
        assert found is None


class TestEnrichmentPipeline:
    """Fix #5: Elasticsearch enrich policy and ingest pipeline generation."""

    def test_enrich_policy_structure(self):
        policy = generate_enrich_policy()
        assert "match" in policy
        assert policy["match"]["match_field"] == "logloom.node_id"
        assert "logloom.module" in policy["match"]["enrich_fields"]
        assert "logloom.tags" in policy["match"]["enrich_fields"]
        assert "logloom.call_children" in policy["match"]["enrich_fields"]

    def test_enrich_policy_custom_names(self):
        policy = generate_enrich_policy(
            policy_name="custom-enrich",
            source_index="my-logloom-idx",
        )
        assert policy["match"]["indices"] == "my-logloom-idx"

    def test_enrich_pipeline_structure(self):
        pipe = generate_enrich_pipeline()
        assert "processors" in pipe
        assert len(pipe["processors"]) == 1

        enrich = pipe["processors"][0]["enrich"]
        assert enrich["policy_name"] == "logloom-enrich"
        assert enrich["field"] == "logloom.node_id"
        assert enrich["target_field"] == "logloom"
        assert enrich["ignore_missing"] is True

    def test_enrich_pipeline_custom_names(self):
        pipe = generate_enrich_pipeline(
            pipeline_name="my-pipeline",
            policy_name="my-policy",
        )
        enrich = pipe["processors"][0]["enrich"]
        assert enrich["policy_name"] == "my-policy"

    def test_pipeline_conditional_script(self):
        pipe = generate_enrich_pipeline()
        enrich = pipe["processors"][0]["enrich"]
        # Should only run when logloom.node_id is present
        assert "ctx?.logloom?.node_id" in enrich["if"]
