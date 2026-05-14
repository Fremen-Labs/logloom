"""Runtime node resolution: maps log call sites → graph node IDs.

Three-tier resolution strategy:
  Tier 1: Exact match on (module, function, message)  — O(1) dict lookup
  Tier 2: Fuzzy match on (function, message)           — O(1) dict lookup
  Tier 3: Template-aware match on (function, pattern)  — O(n) regex scan, cached

Tier 3 fixes the critical gap where runtime log messages contain formatted
values (e.g. "Connecting to Elasticsearch at ['http://...']") that don't match
the build-time message templates (e.g. "Connecting to Elasticsearch at {}...").
"""

import os
import re
import warnings
from typing import Dict, List, Optional, Tuple

from ..graph.model import LogLoomGraph

_DEV_MODE = os.getenv("LOGLOOM_DEV_MODE", "1").lower() in ("1", "true", "yes")


# ── Template → regex conversion ──────────────────────────────────────────────

# Python format-style placeholders: {}, {0}, {name}, {name!r}, {name:.2f}
_PY_FMT_PLACEHOLDER = re.compile(r"\{[^}]*\}")
# C-style format placeholders: %s, %d, %f, %r, %02d, %.2f, %x
_C_FMT_PLACEHOLDER = re.compile(r"%[-+0 #]*\d*\.?\d*[diouxXeEfFgGcrsab%]")


def _template_to_pattern(template: str) -> Optional[re.Pattern]:
    """Convert a message template into a regex pattern for runtime matching.

    Replaces format placeholders ({}, %s, etc.) with ``.*?`` captures.
    Returns None for fully static templates (no placeholders) since those
    are already handled by exact/fuzzy tiers.
    """
    has_py_fmt = _PY_FMT_PLACEHOLDER.search(template)
    has_c_fmt = _C_FMT_PLACEHOLDER.search(template)

    if not has_py_fmt and not has_c_fmt:
        return None  # Static message — exact tiers handle this

    # Escape regex metacharacters in the literal parts
    escaped = re.escape(template)

    # Replace escaped versions of placeholders with a non-greedy wildcard.
    # re.escape will have escaped { } → \{ \}, % → %, etc.
    # We need to replace the escaped placeholder patterns.
    pattern_str = _PY_FMT_PLACEHOLDER.sub(".*?", template)
    pattern_str = _C_FMT_PLACEHOLDER.sub(".*?", pattern_str)

    # Now escape everything except our wildcards
    # Strategy: split on .*?, escape the parts, rejoin
    parts = pattern_str.split(".*?")
    escaped_parts = [re.escape(p) for p in parts]
    final_pattern = ".*?".join(escaped_parts)

    try:
        return re.compile(f"^{final_pattern}$", re.DOTALL)
    except re.error:
        return None


class NodeResolver:
    """Fast runtime resolution of log calls → graph node IDs.

    Three-tier strategy ensures resolution works for:
    - Static messages (Tier 1/2): "Successfully connected to Elasticsearch"
    - Templated messages (Tier 3): "Connecting to Elasticsearch at ['http://...']"
    """

    def __init__(self, graph: LogLoomGraph):
        # Tier 1: exact match on (module, function, message_template)
        self._exact: Dict[Tuple[str, str, str], str] = {}
        # Tier 2: fuzzy match on (function, message_template) only
        self._fuzzy: Dict[Tuple[str, str], str] = {}
        # Tier 3: template-aware regex match on (function, pattern)
        self._template_patterns: Dict[str, List[Tuple[re.Pattern, str]]] = {}

        for node in graph.nodes.values():
            key_exact = (node.module, node.function, node.message_template)
            self._exact[key_exact] = node.node_id

            key_fuzzy = (node.function, node.message_template)
            self._fuzzy[key_fuzzy] = node.node_id

            # Build template patterns grouped by function name for O(1) function
            # lookup then O(k) pattern scan where k = templates per function
            pattern = _template_to_pattern(node.message_template)
            if pattern is not None:
                if node.function not in self._template_patterns:
                    self._template_patterns[node.function] = []
                self._template_patterns[node.function].append((pattern, node.node_id))

        # Cache for Tier 3 matches: formatted_message → node_id
        self._template_cache: Dict[Tuple[str, str], Optional[str]] = {}
        self._cache_max_size = 2048

    def resolve(self, module: str, function: str, message: str) -> Optional[str]:
        """Resolve a runtime log call to a graph node ID.

        Args:
            module:   The calling module name (e.g. 'elastro.core.client')
            function: The calling function name (e.g. 'connect')
            message:  The formatted log message string

        Returns:
            The node ID (e.g. 'll:abc123def456') or None.
        """
        # Tier 1: exact match — O(1)
        node_id = self._exact.get((module, function, message))
        if node_id:
            return node_id

        # Tier 2: fuzzy (function + message only) — O(1)
        node_id = self._fuzzy.get((function, message))
        if node_id:
            if _DEV_MODE:
                warnings.warn(
                    f"LogLoom: fuzzy match for '{message}' in {function}() "
                    f"(module mismatch). Run 'logloom build' to regenerate graph.",
                    stacklevel=3,
                )
            return node_id

        # Tier 3: template-aware regex match — O(k) per function, cached
        return self._resolve_template(function, message)

    def _resolve_template(self, function: str, message: str) -> Optional[str]:
        """Match a formatted message against template regex patterns.

        Cached to avoid repeated regex scans for hot log paths.
        """
        cache_key = (function, message)

        # Check cache first
        if cache_key in self._template_cache:
            return self._template_cache[cache_key]

        result: Optional[str] = None

        # Only scan patterns for this function name — avoids full graph scan
        patterns = self._template_patterns.get(function, [])
        for pattern, node_id in patterns:
            if pattern.match(message):
                result = node_id
                break

        # Cache the result (including None for misses to avoid re-scanning)
        if len(self._template_cache) < self._cache_max_size:
            self._template_cache[cache_key] = result

        return result

