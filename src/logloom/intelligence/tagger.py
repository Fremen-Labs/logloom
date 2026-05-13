"""Issue #14 — Semantic tag auto-inference from AST context.

Derives tags from function names, decorators, module paths, exception blocks,
and message content. Runs as a post-processing pass over the built graph.
"""

from __future__ import annotations

import re
from typing import Dict, List, Set

from ..graph.model import GraphNode, LogLoomGraph

# ── Keyword Mappings ──────────────────────────────────────────────────────────
# Each key is a tag; the value is a set of patterns matched against
# function names, module paths, class names, decorators, and message templates.

_FUNCTION_PATTERNS: Dict[str, List[str]] = {
    "auth":       ["login", "logout", "authenticate", "authorize", "auth",
                   "verify_token", "refresh_token", "check_permission"],
    "security":   ["encrypt", "decrypt", "hash", "verify_signature", "sanitize",
                   "validate_token", "check_csrf"],
    "database":   ["query", "execute", "commit", "rollback", "migrate",
                   "create_table", "drop_table", "upsert", "bulk_insert"],
    "http":       ["request", "response", "fetch", "download", "upload",
                   "get", "post", "put", "patch", "delete"],
    "payment":    ["charge", "refund", "invoice", "subscribe", "checkout",
                   "payment", "billing", "stripe", "process_payment"],
    "lifecycle":  ["startup", "shutdown", "init", "teardown", "cleanup",
                   "on_start", "on_stop", "bootstrap", "dispose"],
    "retry":      ["retry", "backoff", "attempt", "fallback", "circuit_breaker"],
    "cache":      ["cache", "invalidate", "evict", "warm", "memoize"],
    "queue":      ["enqueue", "dequeue", "publish", "subscribe", "consume",
                   "produce", "dispatch", "worker"],
    "validation": ["validate", "check", "assert", "verify", "ensure",
                   "sanitize_input"],
}

_MODULE_PATTERNS: Dict[str, List[str]] = {
    "auth":       ["auth", "iam", "permission", "rbac", "acl"],
    "security":   ["security", "crypto", "ssl", "tls"],
    "database":   ["db", "database", "orm", "repository", "dao", "models"],
    "http":       ["api", "routes", "views", "handlers", "endpoints", "middleware"],
    "payment":    ["payment", "billing", "stripe", "checkout"],
    "lifecycle":  ["startup", "boot", "config", "settings"],
    "queue":      ["queue", "worker", "celery", "tasks", "jobs"],
    "cache":      ["cache", "redis"],
}

_DECORATOR_PATTERNS: Dict[str, List[str]] = {
    "auth":       ["login_required", "requires_auth", "permission_required",
                   "jwt_required"],
    "http":       ["route", "get", "post", "put", "delete", "api_view",
                   "app.route", "router"],
    "retry":      ["retry", "backoff", "tenacity"],
    "cache":      ["cached", "cache", "lru_cache", "memoize"],
    "lifecycle":  ["on_event", "startup", "shutdown", "lifespan"],
    "async":      ["celery", "task", "shared_task"],
}

_MESSAGE_PATTERNS: Dict[str, List[re.Pattern]] = {
    "auth":       [re.compile(r"(?i)(login|logout|auth|token|session|credential)")],
    "security":   [re.compile(r"(?i)(password|secret|key|cert|ssl|tls|encrypt)")],
    "database":   [re.compile(r"(?i)(query|sql|table|row|column|database|migration)")],
    "http":       [re.compile(r"(?i)(request|response|status|endpoint|url|header)")],
    "payment":    [re.compile(r"(?i)(payment|charge|refund|invoice|billing)")],
    "performance":[re.compile(r"(?i)(slow|timeout|latency|elapsed|duration)")],
    "error":      [re.compile(r"(?i)(fail|error|exception|crash|panic|abort)")],
    "retry":      [re.compile(r"(?i)(retry|attempt|backoff|reconnect)")],
}


def infer_tags(graph: LogLoomGraph) -> LogLoomGraph:
    """Enrich every node in the graph with auto-inferred semantic tags.

    This is a pure function — it returns a new graph with updated nodes.
    Existing manual tags are preserved; inferred tags are appended.
    """
    new_nodes = {}
    for node_id, node in graph.nodes.items():
        tags = set(node.semantic_tags)
        tags |= _tags_from_function(node.function)
        tags |= _tags_from_module(node.module)
        tags |= _tags_from_decorators(node)
        tags |= _tags_from_message(node.message_template)
        tags |= _tags_from_context(node)

        new_nodes[node_id] = node.model_copy(update={
            "semantic_tags": sorted(tags)
        })

    return graph.model_copy(update={"nodes": new_nodes})


# ── Internal Helpers ──────────────────────────────────────────────────────────

def _tags_from_function(function_name: str) -> Set[str]:
    """Match function name against known domain patterns."""
    tags: Set[str] = set()
    fn_lower = function_name.lower()
    for tag, patterns in _FUNCTION_PATTERNS.items():
        for pattern in patterns:
            if pattern in fn_lower:
                tags.add(tag)
                break
    return tags


def _tags_from_module(module_path: str) -> Set[str]:
    """Match module path segments against known domain patterns."""
    tags: Set[str] = set()
    mod_lower = module_path.lower()
    for tag, patterns in _MODULE_PATTERNS.items():
        for pattern in patterns:
            if pattern in mod_lower:
                tags.add(tag)
                break
    return tags


def _tags_from_decorators(node: GraphNode) -> Set[str]:
    """Match decorators stored in lexical_parents against known patterns."""
    tags: Set[str] = set()
    # Decorators are currently stored in the lexical_context dict that flows
    # through the scanner → builder pipeline.  However in the GraphNode model,
    # only lexical_parents is persisted.  We check both for robustness.
    for parent in node.lexical_parents:
        parent_lower = parent.lower()
        for tag, patterns in _DECORATOR_PATTERNS.items():
            for pattern in patterns:
                if pattern in parent_lower:
                    tags.add(tag)
                    break
    return tags


def _tags_from_message(message_template: str) -> Set[str]:
    """Regex-match the message template against known domain signals."""
    tags: Set[str] = set()
    for tag, patterns in _MESSAGE_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(message_template):
                tags.add(tag)
                break
    return tags


def _tags_from_context(node: GraphNode) -> Set[str]:
    """Derive tags from structural context (level, lexical_parents)."""
    tags: Set[str] = set()

    # Error-family levels → "error" tag
    if node.level.lower() in ("error", "critical", "exception", "fatal"):
        tags.add("error")

    # Debug level → "debug" tag
    if node.level.lower() == "debug":
        tags.add("debug")

    # Warning → "warning" tag
    if node.level.lower() == "warning":
        tags.add("warning")

    return tags
