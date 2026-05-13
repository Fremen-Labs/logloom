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
