import os
from pathlib import Path
from typing import Optional
from .model import LogLoomGraph

LOGLOOM_ENV_VAR = "LOGLOOM_GRAPH_PATH"
DEFAULT_GRAPH_FILENAME = "logloom-graph.json"

def save_graph(graph: LogLoomGraph, path: Path):
    """Save the graph to a JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(graph.model_dump_json(indent=2))

def load_graph(path: Optional[Path] = None) -> Optional[LogLoomGraph]:
    """
    Load the LogLoomGraph.
    Priority:
    1. Explicit path
    2. Environment variable LOGLOOM_GRAPH_PATH
    3. CWD walk upwards looking for logloom-graph.json
    """
    target_path = None
    
    if path and path.exists():
        target_path = path
    elif LOGLOOM_ENV_VAR in os.environ:
        env_path = Path(os.environ[LOGLOOM_ENV_VAR])
        if env_path.exists():
            target_path = env_path
    else:
        # Walk up from CWD
        current = Path.cwd()
        while True:
            candidate = current / DEFAULT_GRAPH_FILENAME
            if candidate.exists():
                target_path = candidate
                break
            if current.parent == current:
                break
            current = current.parent

    if not target_path:
        return None

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            data = f.read()
        return LogLoomGraph.model_validate_json(data)
    except Exception:
        return None
