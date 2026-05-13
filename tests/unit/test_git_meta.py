"""Tests for Issue #16 — Git metadata integration."""

from logloom.intelligence.git_meta import get_git_metadata, enrich_graph_with_git
from logloom.graph.model import LogLoomGraph


def test_git_metadata_extraction():
    """Should extract git metadata in the logloom repo itself."""
    meta = get_git_metadata()
    # We are inside a git repo, so this should work
    assert meta is not None
    assert meta.commit_sha is not None
    assert len(meta.commit_sha) == 40  # full SHA
    assert meta.branch is not None


def test_enrich_graph_with_git():
    graph = LogLoomGraph(project="test", built_at="2026", nodes={})
    enriched = enrich_graph_with_git(graph)

    assert enriched.commit_sha is not None
    assert enriched.branch is not None
    # Original should be unchanged
    assert graph.commit_sha is None
