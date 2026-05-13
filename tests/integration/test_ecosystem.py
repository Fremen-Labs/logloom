"""Integration tests for Milestone 3: Ecosystem.

Tests the ES CLI commands and multi-language builder integration.
"""

import json
from pathlib import Path
from click.testing import CliRunner
from logloom.cli.main import cli
from logloom.graph.model import LogLoomGraph, GraphNode


def _make_graph_file(tmp_path: Path) -> Path:
    """Create a graph file for testing."""
    graph = LogLoomGraph(
        project="test-es",
        built_at="2026-05-13T00:00:00",
        commit_sha="abc123",
        branch="main",
        nodes={
            "ll:aaa": GraphNode(
                node_id="ll:aaa", file="app.py", module="app",
                function="login", level="info",
                message_template="User login", line=10,
                semantic_tags=["auth"],
            ),
            "ll:bbb": GraphNode(
                node_id="ll:bbb", file="app.py", module="app",
                function="handler", level="error",
                message_template="Request failed", line=20,
                semantic_tags=["http", "error"],
            ),
        },
    )
    path = tmp_path / "test-graph.json"
    graph.save(str(path))
    return path


def test_es_mapping_cli(tmp_path: Path):
    """Test logloom es mapping command."""
    runner = CliRunner()

    # Component template
    result = runner.invoke(cli, ["es", "mapping", "--type", "component"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert "template" in parsed

    # Index template to file
    out = tmp_path / "mapping.json"
    result = runner.invoke(cli, [
        "es", "mapping", "--type", "index",
        "--index-patterns", "logs-*",
        "--output", str(out),
    ])
    assert result.exit_code == 0
    assert out.exists()
    parsed = json.loads(out.read_text())
    assert parsed["index_patterns"] == ["logs-*"]


def test_es_export_cli(tmp_path: Path):
    """Test logloom es export command."""
    graph_path = _make_graph_file(tmp_path)
    runner = CliRunner()

    out = tmp_path / "export.ndjson"
    result = runner.invoke(cli, [
        "es", "export",
        "--graph-path", str(graph_path),
        "--index", "test-enrichment",
        "--output", str(out),
    ])
    assert result.exit_code == 0
    assert out.exists()

    lines = out.read_text().strip().split("\n")
    assert len(lines) == 4  # 2 docs × 2 lines each

    # Verify action lines
    action = json.loads(lines[0])
    assert action["index"]["_index"] == "test-enrichment"


def test_multi_language_build_python(tmp_path: Path):
    """Build with explicit --languages python still works."""
    app_file = tmp_path / "app.py"
    app_file.write_text('''
import logging
logger = logging.getLogger(__name__)

def hello():
    logger.info("Hello world")
''')

    runner = CliRunner()
    graph_path = tmp_path / "graph.json"
    result = runner.invoke(cli, [
        "build",
        "--source", str(tmp_path),
        "--output", str(graph_path),
        "--languages", "python",
        "--no-git",
    ])
    assert result.exit_code == 0
    assert "1 nodes" in result.output
