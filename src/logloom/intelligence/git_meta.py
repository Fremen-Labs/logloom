"""Issue #16 — Git integration for logloom build.

Embeds commit SHA, branch name, and author into graph metadata.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional

from ..graph.model import LogLoomGraph


@dataclass
class GitMetadata:
    """Container for git metadata extracted from the repository."""
    commit_sha: Optional[str] = None
    branch: Optional[str] = None
    author: Optional[str] = None
    dirty: bool = False


def get_git_metadata() -> Optional[GitMetadata]:
    """Extract git metadata from the current working directory.

    Returns None if we are not inside a git repository.
    Never raises — git failures are silently swallowed.
    """
    try:
        sha = _run_git("rev-parse", "HEAD")
        if not sha:
            return None

        branch = _run_git("rev-parse", "--abbrev-ref", "HEAD")
        author = _run_git("log", "-1", "--format=%an")

        # Check if working tree is dirty
        status = _run_git("status", "--porcelain")
        dirty = bool(status and status.strip())

        return GitMetadata(
            commit_sha=sha,
            branch=branch or None,
            author=author or None,
            dirty=dirty,
        )
    except Exception:
        return None


def enrich_graph_with_git(graph: LogLoomGraph) -> LogLoomGraph:
    """Enrich the graph model with git metadata.

    Returns a new graph with commit_sha and branch populated.
    """
    meta = get_git_metadata()
    if not meta:
        return graph

    return graph.model_copy(update={
        "commit_sha": meta.commit_sha,
        "branch": meta.branch,
    })


def _run_git(*args: str) -> Optional[str]:
    """Run a git command and return stripped stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
