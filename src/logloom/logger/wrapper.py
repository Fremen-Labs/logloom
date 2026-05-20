import sys
import structlog
from typing import Any
from ..graph.store import load_graph
from .resolver import NodeResolver

class LogLoomLogger:
    def __init__(self, name: str):
        self.name = name
        self._logger = structlog.get_logger(name)
        
        # Load graph gracefully
        self.graph = load_graph()
        self.resolver = NodeResolver(self.graph) if self.graph else None

    def _enrich_event(self, level: str, event: str, **kw: Any) -> Any:
        if not self.resolver:
            # Graceful degradation: log normally
            return getattr(self._logger, level)(event, **kw)
        
        try:
            # Traverse back 2 frames to get the caller's context
            # Frame 0: _enrich_event
            # Frame 1: info/warning/etc.
            # Frame 2: actual caller
            frame = sys._getframe(2)
            module = frame.f_globals.get("__name__", "unknown")
            function = frame.f_code.co_name
            
            node_id = self.resolver.resolve(module, function, event)
            
            if node_id:
                kw["logloom.node_id"] = node_id
                node = self.graph.nodes.get(node_id)
                if node:
                    if node.lexical_parents:
                        kw["logloom.traversal"] = node.lexical_parents
                    if node.call_parents:
                        kw["logloom.call_parents"] = node.call_parents
                    if node.call_children:
                        kw["logloom.call_children"] = node.call_children
                    if node.call_parent_names:
                        kw["logloom.call_parent_names"] = node.call_parent_names
                    if node.call_child_names:
                        kw["logloom.call_child_names"] = node.call_child_names
                    if node.signature:
                        kw["logloom.signature"] = node.signature.model_dump()
        except Exception:
            # Safety net: never crash the application because of logging
            pass
            
        return getattr(self._logger, level)(event, **kw)

    def debug(self, event: str, **kw: Any) -> Any:
        return self._enrich_event("debug", event, **kw)

    def info(self, event: str, **kw: Any) -> Any:
        return self._enrich_event("info", event, **kw)

    def warning(self, event: str, **kw: Any) -> Any:
        return self._enrich_event("warning", event, **kw)
        
    def error(self, event: str, **kw: Any) -> Any:
        return self._enrich_event("error", event, **kw)

    def exception(self, event: str, **kw: Any) -> Any:
        return self._enrich_event("exception", event, **kw)

    def critical(self, event: str, **kw: Any) -> Any:
        return self._enrich_event("critical", event, **kw)

def get_logger(name: str) -> LogLoomLogger:
    return LogLoomLogger(name)
