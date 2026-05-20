"""Issue #22 — OpenTelemetry Log Bridge.

Provides a structlog processor and a stdlib logging handler that inject
LogLoom semantic fields into OpenTelemetry LogRecord attributes.

This enables correlation between OTEL traces and LogLoom's code-structure graph:
a log event carries both ``trace_id`` (runtime execution path) and
``logloom.node_id`` (static code structure).

Two integration points:
  1. ``LogLoomOTELProcessor`` — structlog processor for structlog pipelines
  2. ``LogLoomOTELHandler``  — stdlib logging handler for traditional logging
"""

from __future__ import annotations

import sys
from typing import Any, Dict, Optional

from ..graph.store import load_graph
from ..logger.resolver import NodeResolver
from ..graph.model import LogLoomGraph


# ── Attribute keys (OTEL semantic conventions) ────────────────────────────────
# These follow the OTEL attribute naming convention: "logloom.*"
ATTR_NODE_ID = "logloom.node_id"
ATTR_MODULE = "logloom.module"
ATTR_FUNCTION = "logloom.function"
ATTR_FILE = "logloom.file"
ATTR_LINE = "logloom.line"
ATTR_TAGS = "logloom.tags"
ATTR_TRAVERSAL = "logloom.traversal"
ATTR_CALL_PARENTS = "logloom.call_parents"
ATTR_CALL_CHILDREN = "logloom.call_children"
ATTR_CALL_PARENT_NAMES = "logloom.call_parent_names"
ATTR_CALL_CHILD_NAMES = "logloom.call_child_names"
ATTR_SIGNATURE = "logloom.signature"
ATTR_GRAPH_VERSION = "logloom.graph_version"
ATTR_COMMIT_SHA = "logloom.commit_sha"


class LogLoomOTELProcessor:
    """structlog processor that enriches log events with OTEL-compatible LogLoom attributes.

    Usage::

        import structlog
        from logloom.otel.bridge import LogLoomOTELProcessor

        structlog.configure(
            processors=[
                LogLoomOTELProcessor(),
                structlog.dev.ConsoleRenderer(),
            ]
        )
    """

    def __init__(self, graph: Optional[LogLoomGraph] = None):
        self._graph = graph or load_graph()
        self._resolver = NodeResolver(self._graph) if self._graph else None

    def __call__(
        self,
        logger: Any,
        method_name: str,
        event_dict: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not self._resolver:
            return event_dict

        try:
            # Resolve caller context
            frame = sys._getframe(6)  # structlog wraps several layers deep
            module = frame.f_globals.get("__name__", "unknown")
            function = frame.f_code.co_name
            event = event_dict.get("event", "")

            node_id = self._resolver.resolve(module, function, str(event))
            if node_id and self._graph:
                node = self._graph.nodes.get(node_id)
                if node:
                    event_dict[ATTR_NODE_ID] = node_id
                    event_dict[ATTR_MODULE] = node.module
                    event_dict[ATTR_FUNCTION] = node.function
                    event_dict[ATTR_FILE] = node.file
                    event_dict[ATTR_LINE] = node.line
                    event_dict[ATTR_TAGS] = node.semantic_tags
                    event_dict[ATTR_GRAPH_VERSION] = self._graph.built_at
                    if node.lexical_parents:
                        event_dict[ATTR_TRAVERSAL] = node.lexical_parents
                    if node.call_parents:
                        event_dict[ATTR_CALL_PARENTS] = node.call_parents
                    if node.call_children:
                        event_dict[ATTR_CALL_CHILDREN] = node.call_children
                    if node.call_parent_names:
                        event_dict[ATTR_CALL_PARENT_NAMES] = node.call_parent_names
                    if node.call_child_names:
                        event_dict[ATTR_CALL_CHILD_NAMES] = node.call_child_names
                    if node.signature:
                        event_dict[ATTR_SIGNATURE] = node.signature.model_dump()
                    if self._graph.commit_sha:
                        event_dict[ATTR_COMMIT_SHA] = self._graph.commit_sha
        except Exception:
            pass  # Never crash the logging pipeline

        return event_dict


class LogLoomOTELHandler:
    """Mixin for stdlib logging that injects LogLoom attributes into LogRecord.

    This is designed to work with the OTEL SDK's ``LoggingHandler`` which
    reads ``LogRecord`` attributes and maps them to OTEL ``LogRecord``
    resource attributes.

    Usage::

        import logging
        from logloom.otel.bridge import LogLoomOTELHandler

        handler = LogLoomOTELHandler()
        handler.install()  # patches logging.Logger.makeRecord
    """

    def __init__(self, graph: Optional[LogLoomGraph] = None):
        self._graph = graph or load_graph()
        self._resolver = NodeResolver(self._graph) if self._graph else None
        self._original_makeRecord = None

    def install(self):
        """Monkey-patch ``logging.Logger.makeRecord`` to inject LogLoom attributes.

        Safe to call multiple times — subsequent calls are no-ops.
        """
        import logging

        # Idempotency guard: don't re-capture a patched function as the original
        if self._original_makeRecord is not None:
            return

        original = logging.Logger.makeRecord
        resolver = self._resolver
        graph = self._graph

        def patched_makeRecord(self_logger, name, level, fn, lno, msg, args, exc_info,
                                func=None, extra=None, sinfo=None):
            record = original(self_logger, name, level, fn, lno, msg, args, exc_info,
                            func=func, extra=extra, sinfo=sinfo)

            if resolver and graph:
                try:
                    module = record.module if hasattr(record, "module") else name
                    function = record.funcName or ""
                    message = str(record.getMessage()) if args else str(msg)

                    node_id = resolver.resolve(module, function, message)
                    if node_id:
                        record.logloom_node_id = node_id
                        node = graph.nodes.get(node_id)
                        if node:
                            record.logloom_module = node.module
                            record.logloom_function = node.function
                            record.logloom_tags = node.semantic_tags
                            record.logloom_file = node.file
                            record.logloom_line = node.line
                            if node.call_parents:
                                record.logloom_call_parents = node.call_parents
                            if node.call_children:
                                record.logloom_call_children = node.call_children
                            if node.call_parent_names:
                                record.logloom_call_parent_names = node.call_parent_names
                            if node.call_child_names:
                                record.logloom_call_child_names = node.call_child_names
                            if node.signature:
                                record.logloom_signature = node.signature.model_dump()
                except Exception:
                    pass  # Never crash

            return record

        logging.Logger.makeRecord = patched_makeRecord
        self._original_makeRecord = original

    def uninstall(self):
        """Restore the original ``makeRecord``."""
        import logging

        if self._original_makeRecord:
            logging.Logger.makeRecord = self._original_makeRecord
            self._original_makeRecord = None


def get_otel_resource_attributes(graph: LogLoomGraph) -> Dict[str, Any]:
    """Return OTEL resource-level attributes for the LogLoom graph.

    These should be set on the OTEL ``Resource`` at application startup::

        from opentelemetry.sdk.resources import Resource
        from logloom.otel.bridge import get_otel_resource_attributes

        resource = Resource.create(get_otel_resource_attributes(graph))
    """
    attrs: Dict[str, Any] = {
        "logloom.project": graph.project,
        "logloom.schema_version": graph.schema_version,
        "logloom.graph_built_at": graph.built_at,
        "logloom.node_count": len(graph.nodes),
    }
    if graph.commit_sha:
        attrs["logloom.commit_sha"] = graph.commit_sha
    if graph.branch:
        attrs["logloom.branch"] = graph.branch
    return attrs
