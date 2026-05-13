import warnings
from typing import Dict, Tuple, Optional
from ..graph.model import LogLoomGraph

_DEV_MODE = True  # Can be controlled by an env var or config later

class NodeResolver:
    """Fast runtime resolution of log calls → graph node IDs."""

    def __init__(self, graph: LogLoomGraph):
        # Primary lookup: exact match on (module, function, message_template)
        self._exact: Dict[Tuple[str, str, str], str] = {}
        # Fuzzy lookup: match on (function, message_template) only
        self._fuzzy: Dict[Tuple[str, str], str] = {}

        for node in graph.nodes.values():
            key_exact = (node.module, node.function, node.message_template)
            self._exact[key_exact] = node.node_id
            
            key_fuzzy = (node.function, node.message_template)
            # If multiple fuzzy matches exist, we could store a list. 
            # For phase 1, just keep the first one found or overwrite.
            self._fuzzy[key_fuzzy] = node.node_id

    def resolve(self, module: str, function: str, message: str) -> Optional[str]:
        """O(1) dict lookup with fuzzy fallback."""
        # Tier 1: exact match
        node_id = self._exact.get((module, function, message))
        if node_id:
            return node_id

        # Tier 2: fuzzy (function + message only)
        node_id = self._fuzzy.get((function, message))
        if node_id:
            if _DEV_MODE:
                warnings.warn(
                    f"LogLoom: fuzzy match for '{message}' in {function}() "
                    f"(module mismatch). Run 'logloom build' to regenerate graph.",
                    stacklevel=3,
                )
            return node_id

        return None
