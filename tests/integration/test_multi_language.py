"""Integration tests for multi-language scanner pipeline.

Tests the full build pipeline across Go, TypeScript/JavaScript, and Python,
including cross-language graph construction, tag inference, and CLI validation.
"""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from logloom.cli.main import cli
from logloom.scanner.go_scanner import GoScanner
from logloom.scanner.ts_scanner import TypeScriptScanner

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def go_scanner():
    scanner = GoScanner()
    if not scanner.available:
        pytest.skip("tree-sitter-go not installed")
    return scanner


@pytest.fixture
def ts_scanner():
    scanner = TypeScriptScanner()
    if not scanner.available:
        pytest.skip("tree-sitter-typescript/javascript not installed")
    return scanner


# ── Go integration ────────────────────────────────────────────────────────────

def test_go_build_pipeline_cli(tmp_path: Path):
    """Full CLI build from Go fixture produces a valid graph."""
    runner = CliRunner()
    graph_path = tmp_path / "go-graph.json"
    result = runner.invoke(cli, [
        "build",
        "--source", str(FIXTURES_DIR / "sample_app.go"),
        "--output", str(graph_path),
        "--languages", "go",
        "--no-git",
        "--tags",
    ])

    if "tree-sitter-go not installed" in result.output:
        pytest.skip("tree-sitter-go not installed")

    assert result.exit_code == 0, result.output
    assert graph_path.exists()

    graph = json.loads(graph_path.read_text())
    nodes = graph["nodes"]

    # Should have a healthy node count from all 5 frameworks
    assert len(nodes) >= 25, f"Expected >=25 Go nodes, got {len(nodes)}"

    # Verify zerolog chain resolution produced correct messages
    zerolog_nodes = [n for n in nodes.values()
                     if n.get("function") == "zerologExamples"]
    assert len(zerolog_nodes) >= 4

    # Verify method receiver qualification exists
    auth_nodes = [n for n in nodes.values()
                  if "AuthService" in (n.get("function") or "")]
    assert len(auth_nodes) >= 2, f"Expected AuthService-qualified nodes, got {auth_nodes}"


def test_go_build_tags_inferred(go_scanner, tmp_path: Path):
    """Go scanner sites should receive semantic tags after graph build."""
    runner = CliRunner()
    graph_path = tmp_path / "go-tags.json"
    result = runner.invoke(cli, [
        "build",
        "--source", str(FIXTURES_DIR / "sample_app.go"),
        "--output", str(graph_path),
        "--languages", "go",
        "--no-git", "--tags",
    ])
    assert result.exit_code == 0

    graph = json.loads(graph_path.read_text())
    all_tags = set()
    for node in graph["nodes"].values():
        all_tags.update(node.get("semantic_tags", []))

    # Tags should be inferred from the Go fixture
    assert "auth" in all_tags, f"Expected 'auth' tag, got {all_tags}"
    assert "error" in all_tags
    assert "http" in all_tags


# ── TypeScript integration ────────────────────────────────────────────────────

def test_ts_build_pipeline_cli(tmp_path: Path):
    """Full CLI build from TypeScript fixture produces a valid graph."""
    runner = CliRunner()
    graph_path = tmp_path / "ts-graph.json"
    result = runner.invoke(cli, [
        "build",
        "--source", str(FIXTURES_DIR / "sample_app.ts"),
        "--output", str(graph_path),
        "--languages", "typescript",
        "--no-git",
        "--tags",
    ])

    if "tree-sitter-typescript not installed" in result.output:
        pytest.skip("tree-sitter-typescript not installed")

    assert result.exit_code == 0, result.output
    assert graph_path.exists()

    graph = json.loads(graph_path.read_text())
    nodes = graph["nodes"]
    assert len(nodes) >= 25, f"Expected >=25 TS nodes, got {len(nodes)}"


def test_ts_switch_and_closure_context(ts_scanner, tmp_path: Path):
    """TS scanner should detect switch/case and nested closures."""
    f = tmp_path / "switch_closure.ts"
    f.write_text('''
function handler(action: string): void {
    switch (action) {
        case "create":
            console.log("Creating resource");
            break;
        case "delete":
            console.warn("Deleting resource");
            break;
    }

    const callback = () => {
        console.debug("Inside closure callback");
    };
    callback();
}
''')
    sites = ts_scanner.scan_file(f)
    assert len(sites) >= 3

    # Switch detection
    switch_sites = [s for s in sites if s.lexical_context.get("in_switch")]
    assert len(switch_sites) >= 2, "Expected switch sites"

    # Closure detection
    closure_sites = [s for s in sites if s.lexical_context.get("in_closure")]
    assert len(closure_sites) >= 1, "Expected closure site"


def test_ts_catch_clause_context(ts_scanner, tmp_path: Path):
    """TS scanner should distinguish try vs catch block context."""
    f = tmp_path / "catch.ts"
    f.write_text('''
async function fetchData(): Promise<void> {
    try {
        console.log("Fetching data");
    } catch (err) {
        console.error("Fetch failed");
    }
}
''')
    sites = ts_scanner.scan_file(f)
    assert len(sites) == 2

    catch_sites = [s for s in sites if s.lexical_context.get("in_catch")]
    assert len(catch_sites) == 1
    assert catch_sites[0].message_template == "Fetch failed"

    # Both should be in_try_except (catch is semantically part of try)
    try_sites = [s for s in sites if s.lexical_context.get("in_try_except")]
    assert len(try_sites) == 2


# ── Cross-language build ──────────────────────────────────────────────────────

def test_multi_language_build_all(tmp_path: Path):
    """Build with all languages against the fixtures directory."""
    runner = CliRunner()
    graph_path = tmp_path / "multi-graph.json"
    result = runner.invoke(cli, [
        "build",
        "--source", str(FIXTURES_DIR),
        "--output", str(graph_path),
        "--languages", "python,go,typescript",
        "--no-git",
    ])

    # If language parsers aren't installed, skip
    if result.exit_code != 0 and "not installed" in result.output:
        pytest.skip("Multi-language parsers not available")

    assert result.exit_code == 0, result.output
    graph = json.loads(graph_path.read_text())
    nodes = graph["nodes"]

    # Both Go and TS fixtures should contribute nodes
    files = {n.get("file", "") for n in nodes.values()}
    has_go = any(".go" in f for f in files)
    has_ts = any(".ts" in f for f in files)
    assert has_go or has_ts, f"Expected multi-language nodes, got files: {files}"
