"""Tests for logloom init CLI command."""

from pathlib import Path
from click.testing import CliRunner
from logloom.cli.main import cli


def test_init_command_creates_files(tmp_path: Path, monkeypatch):
    # Mock Path.cwd() to return our temp directory so that init creates files there
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    
    runner = CliRunner()
    
    # 1. Run first time
    result = runner.invoke(cli, ["init"], input="my-test-project\n")
    assert result.exit_code == 0
    assert "Created .logloomignore" in result.output
    assert "Created .logloomrc.toml" in result.output
    assert "LogLoom initialized successfully" in result.output
    
    ignore_file = tmp_path / ".logloomignore"
    rc_file = tmp_path / ".logloomrc.toml"
    
    assert ignore_file.exists()
    assert rc_file.exists()
    assert 'project_name = "my-test-project"' in rc_file.read_text()

    # 2. Run second time without force
    result2 = runner.invoke(cli, ["init"], input="my-other-project\n")
    assert result2.exit_code == 0
    assert ".logloomignore already exists" in result2.output
    assert ".logloomrc.toml already exists" in result2.output
    
    # 3. Run with --force
    result3 = runner.invoke(cli, ["init", "--force"], input="overwritten-project\n")
    assert result3.exit_code == 0
    assert "Created .logloomignore" in result3.output
    assert "Created .logloomrc.toml" in result3.output
    assert 'project_name = "overwritten-project"' in rc_file.read_text()
