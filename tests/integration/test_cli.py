"""Integration tests for LogLoom CLI commands."""

import json
from pathlib import Path
from click.testing import CliRunner
from logloom.cli.main import cli

def test_lint_and_graph_commands(tmp_path: Path):
    runner = CliRunner()
    
    # Create a sample app
    app_file = tmp_path / "app.py"
    app_file.write_text("""
import logging
logger = logging.getLogger(__name__)

def do_login():
    logger.info("User login attempt")
    
def do_logout():
    logger.info("User logout")
""")
    
    graph_path = tmp_path / "logloom-graph.json"
    
    # 1. Build the graph
    result = runner.invoke(cli, ["build", "--source", str(tmp_path), "--output", str(graph_path)])
    assert result.exit_code == 0
    assert "Built graph: 2 nodes" in result.output
    
    # 2. Test graph stats
    result = runner.invoke(cli, ["graph", "stats", "--graph-path", str(graph_path)])
    assert result.exit_code == 0
    assert "Graph Overview" in result.output
    assert "Log sites" in result.output
    assert "2" in result.output
    
    # 3. Test graph show
    result = runner.invoke(cli, ["graph", "show", "--graph-path", str(graph_path)])
    assert result.exit_code == 0
    assert "User login attempt" in result.output
    
    # 4. Test graph find
    result = runner.invoke(cli, ["graph", "find", "logout", "--graph-path", str(graph_path)])
    assert result.exit_code == 0
    assert "User logout" in result.output
    
    # 5. Test lint (in sync)
    result = runner.invoke(cli, ["lint", "--source", str(tmp_path), "--graph-path", str(graph_path)])
    assert result.exit_code == 0
    assert "All 2 log sites are tracked." in result.output
    
    # 6. Modify app to add untracked site and remove a tracked site
    app_file.write_text("""
import logging
logger = logging.getLogger(__name__)

def do_login():
    logger.info("User login attempt")

# Adding lines to shift the line number
    
def new_feature():
    logger.warning("Something new")
""")
    
    # 7. Test lint (out of sync)
    result = runner.invoke(cli, ["lint", "--source", str(tmp_path), "--graph-path", str(graph_path), "--strict"])
    assert result.exit_code == 1
    assert "1 Untracked Log Sites" in result.output
    assert "Something new" in result.output
    assert "1 Stale Graph Entries" in result.output
    
    # 8. Test diff
    # Rebuild new graph
    new_graph_path = tmp_path / "logloom-graph-new.json"
    runner.invoke(cli, ["build", "--source", str(tmp_path), "--output", str(new_graph_path)])
    
    result = runner.invoke(cli, ["diff", str(graph_path), str(new_graph_path)])
    assert result.exit_code == 0
    assert "Added (1)" in result.output
    assert "Removed (1)" in result.output


def test_cli_coverage_options(tmp_path: Path):
    runner = CliRunner()
    
    # 50% coverage code (1/2 functions has logs)
    app_file = tmp_path / "app.py"
    app_file.write_text("""
import logging
logger = logging.getLogger(__name__)

def instrumented():
    logger.info("Logging here")

def silent():
    pass
""")

    graph_path = tmp_path / "logloom-graph.json"

    # 1. min-coverage check passes (50% >= 40%)
    result = runner.invoke(cli, ["build", "--source", str(tmp_path), "--output", str(graph_path), "--min-coverage", "40"])
    assert result.exit_code == 0
    assert "Built graph" in result.output

    # 2. min-coverage check fails (50% < 60%)
    result = runner.invoke(cli, ["build", "--source", str(tmp_path), "--output", str(graph_path), "--min-coverage", "60"])
    assert result.exit_code == 1
    assert "Build failed" in result.output
    assert "coverage 50.0% is below required minimum threshold 60.0%" in result.output

    # 3. stats shows coverage table and uninstrumented functions list
    result = runner.invoke(cli, ["graph", "stats", "--graph-path", str(graph_path)])
    assert result.exit_code == 0
    assert "Log Coverage Metrics" in result.output
    assert "Coverage Percentage" in result.output
    assert "50.0%" in result.output
    assert "Uninstrumented Functions" in result.output
    assert "silent" in result.output


def test_cli_external_imports(tmp_path: Path):
    runner = CliRunner()

    src_dir = tmp_path / "src" / "myproj"
    src_dir.mkdir(parents=True)
    
    # App file that imports stdlib, third-party, and relative modules
    app_file = src_dir / "app.py"
    app_file.write_text("""
import json
import sys
from .models import User
""")

    models_file = src_dir / "models.py"
    models_file.write_text("""
class User:
    pass
""")

    graph_path = tmp_path / "logloom-graph.json"

    # 1. Default run (only internal imports)
    result = runner.invoke(cli, ["build", "--source", str(tmp_path), "--output", str(graph_path)])
    assert result.exit_code == 0
    with open(graph_path) as f:
        graph_data = json.load(f)
    
    # Internal import (myproj.models) should exist, external (json, sys) should be filtered out
    assert "myproj.app" in graph_data["imports"]
    # Check that myproj.models is in the import list of myproj.app
    assert "myproj.models" in graph_data["imports"]["myproj.app"]
    assert "json" not in graph_data["imports"]["myproj.app"]
    assert "sys" not in graph_data["imports"]["myproj.app"]

    # 2. Run with --external-imports included
    result = runner.invoke(cli, ["build", "--source", str(tmp_path), "--output", str(graph_path), "--external-imports"])
    assert result.exit_code == 0
    with open(graph_path) as f:
        graph_data_external = json.load(f)

    assert "myproj.app" in graph_data_external["imports"]
    # Both relative and stdlib/external imports should be included
    assert ".models" in graph_data_external["imports"]["myproj.app"]
    assert "json" in graph_data_external["imports"]["myproj.app"]
    assert "sys" in graph_data_external["imports"]["myproj.app"]


def test_cli_diff_advanced(tmp_path: Path):
    runner = CliRunner()
    
    # 1. Base graph
    graph_data = {
        "schema_version": "1.2",
        "project": "test-diff",
        "built_at": "2026-05-20T00:00:00Z",
        "nodes": {
            "ll:node1": {
                "node_id": "ll:node1",
                "file": "app.py",
                "module": "app",
                "function": "func1",
                "level": "info",
                "message_template": "hello",
                "line": 5
            }
        }
    }
    
    graph_old = tmp_path / "graph_old.json"
    with open(graph_old, "w") as f:
        json.dump(graph_data, f)
        
    # 2. No changes test
    result = runner.invoke(cli, ["diff", str(graph_old), str(graph_old)])
    assert result.exit_code == 0
    assert "No changes detected" in result.output
    
    # 3. Removed node + strict test
    graph_data_removed = {
        "schema_version": "1.2",
        "project": "test-diff",
        "built_at": "2026-05-20T00:00:00Z",
        "nodes": {}
    }
    graph_removed = tmp_path / "graph_removed.json"
    with open(graph_removed, "w") as f:
        json.dump(graph_data_removed, f)
        
    result_strict = runner.invoke(cli, ["diff", str(graph_old), str(graph_removed), "--strict"])
    assert result_strict.exit_code == 1
    assert "Removed (1)" in result_strict.output
    
    # 4. Moved node test
    graph_data_moved = {
        "schema_version": "1.2",
        "project": "test-diff",
        "built_at": "2026-05-20T00:00:00Z",
        "nodes": {
            "ll:node1": {
                "node_id": "ll:node1",
                "file": "other_file.py",
                "module": "app",
                "function": "func1",
                "level": "info",
                "message_template": "hello",
                "line": 20
            }
        }
    }
    graph_moved = tmp_path / "graph_moved.json"
    with open(graph_moved, "w") as f:
        json.dump(graph_data_moved, f)
        
    result_moved = runner.invoke(cli, ["diff", str(graph_old), str(graph_moved)])
    assert result_moved.exit_code == 0
    assert "Moved (1)" in result_moved.output
    assert "other_file.py:20" in result_moved.output
    
    # 5. Modified node test
    graph_data_modified = {
        "schema_version": "1.2",
        "project": "test-diff",
        "built_at": "2026-05-20T00:00:00Z",
        "nodes": {
            "ll:node1": {
                "node_id": "ll:node1",
                "file": "app.py",
                "module": "app",
                "function": "func1",
                "level": "error",
                "message_template": "hello modified",
                "line": 5
            }
        }
    }
    graph_modified = tmp_path / "graph_modified.json"
    with open(graph_modified, "w") as f:
        json.dump(graph_data_modified, f)
        
    result_modified = runner.invoke(cli, ["diff", str(graph_old), str(graph_modified)])
    assert result_modified.exit_code == 0
    assert "Modified (1)" in result_modified.output
    assert "level:" in result_modified.output
    assert "message:" in result_modified.output


def test_cli_graph_v2_subcommands(tmp_path: Path):
    runner = CliRunner()
    
    # Create sample codebase with imports and models
    src_dir = tmp_path / "src" / "myproj"
    src_dir.mkdir(parents=True)
    
    app_file = src_dir / "app.py"
    app_file.write_text("""
import logging
from .models import User

logger = logging.getLogger(__name__)

def do_login():
    logger.info("User logging in")
""")

    models_file = src_dir / "models.py"
    models_file.write_text("""
from dataclasses import dataclass

@dataclass
class User:
    username: str
    age: int
""")

    graph_path = tmp_path / "logloom-graph.json"
    html_output = tmp_path / "logloom-graph.html"

    # Build the graph first
    result = runner.invoke(cli, ["build", "--source", str(tmp_path), "--output", str(graph_path), "--external-imports"])
    assert result.exit_code == 0

    # 1. Test graph imports command
    result = runner.invoke(cli, ["graph", "imports", "--graph-path", str(graph_path)])
    assert result.exit_code == 0
    assert "Import Dependency Tree" in result.output
    assert "myproj.app" in result.output

    # 2. Test graph models command
    result = runner.invoke(cli, ["graph", "models", "--graph-path", str(graph_path)])
    assert result.exit_code == 0
    assert "Extracted Data Models" in result.output
    assert "User" in result.output

    # 3. Test graph viz command
    result = runner.invoke(cli, ["graph", "viz", "--graph-path", str(graph_path), "--output", str(html_output)])
    assert result.exit_code == 0
    assert "Generated interactive visualization" in result.output
    assert html_output.exists()
    
    # Verify HTML content
    html_content = html_output.read_text(encoding="utf-8")
    assert "LogLoom Graph Visualization" in html_content
    assert "GRAPH_DATA_PLACEHOLDER" not in html_content  # Should be replaced
    assert "User logging in" in html_content
