import os
import sys
from pathlib import Path
from typing import Optional
from .model import LogLoomGraph

LOGLOOM_ENV_VAR = "LOGLOOM_GRAPH_PATH"
DEFAULT_GRAPH_FILENAME = "logloom-graph.json"


def save_graph(graph: LogLoomGraph, path: Path) -> None:
    """Save the graph to a JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(graph.model_dump_json(indent=2))


def load_graph(path: Optional[Path] = None) -> Optional[LogLoomGraph]:
    """Load the LogLoomGraph using a multi-strategy discovery chain.

    Priority:
      1. Explicit ``path`` argument
      2. ``LOGLOOM_GRAPH_PATH`` environment variable
      3. CWD walk upwards looking for ``logloom-graph.json``
      4. Caller's file directory walk upwards (for installed packages)
      5. Graceful degradation — return None

    Each strategy is tried in sequence. The first file that exists wins.
    """
    target_path = _discover_graph(path)

    if not target_path:
        return None

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            data = f.read()
        return LogLoomGraph.model_validate_json(data)
    except Exception:
        return None


def _discover_graph(explicit_path: Optional[Path] = None) -> Optional[Path]:
    """Multi-strategy graph file discovery."""

    # Strategy 1: Explicit path
    if explicit_path and explicit_path.exists():
        return explicit_path

    # Strategy 2: Environment variable
    env_val = os.environ.get(LOGLOOM_ENV_VAR)
    if env_val:
        env_path = Path(env_val)
        if env_path.exists():
            return env_path

    # Strategy 3: Walk up from CWD
    found = _walk_up_for_graph(Path.cwd())
    if found:
        return found

    # Strategy 4: Walk up from the caller's module directory
    # This handles the case where the app is installed as a package and CWD
    # is not the project root, but logloom-graph.json sits next to the code.
    try:
        frame = sys._getframe(2)  # Caller of load_graph's caller
        caller_file = frame.f_globals.get("__file__")
        if caller_file:
            caller_dir = Path(caller_file).resolve().parent
            found = _walk_up_for_graph(caller_dir)
            if found:
                return found
    except (ValueError, AttributeError):
        pass

    return None


def _walk_up_for_graph(start: Path) -> Optional[Path]:
    """Walk up from ``start`` looking for logloom-graph.json."""
    current = start.resolve()
    for _ in range(20):  # Safety limit to prevent infinite loops
        candidate = current / DEFAULT_GRAPH_FILENAME
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None

