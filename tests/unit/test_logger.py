"""Unit tests for the LogLoomLogger wrapper."""

import pytest
import structlog
from unittest.mock import MagicMock
from logloom.logger.wrapper import get_logger, LogLoomLogger
from logloom.graph.model import LogLoomGraph, GraphNode, FunctionSignature, Parameter


def test_logger_graceful_degradation(monkeypatch):
    """Test logger when no graph is present: should log normally and not enrich/crash."""
    # Force load_graph to return None
    monkeypatch.setattr("logloom.logger.wrapper.load_graph", lambda: None)
    
    mock_structlog = MagicMock()
    monkeypatch.setattr(structlog, "get_logger", lambda name: mock_structlog)
    
    logger = get_logger("my_service")
    assert logger.graph is None
    assert logger.resolver is None
    
    # Check all logging methods execute without crash
    logger.debug("debug message", key="val")
    mock_structlog.debug.assert_called_once_with("debug message", key="val")
    
    logger.info("info message")
    mock_structlog.info.assert_called_once_with("info message")
    
    logger.warning("warning message")
    mock_structlog.warning.assert_called_once_with("warning message")
    
    logger.error("error message")
    mock_structlog.error.assert_called_once_with("error message")
    
    logger.exception("exception message")
    mock_structlog.exception.assert_called_once_with("exception message")
    
    logger.critical("critical message")
    mock_structlog.critical.assert_called_once_with("critical message")


def test_logger_enrichment(monkeypatch):
    """Test logger when graph is present: should add node_id, traversal, and v2 enrichment fields."""
    nodes = {
        "ll:auth_ok": GraphNode(
            node_id="ll:auth_ok",
            file="tests/unit/test_logger.py",
            module=__name__,
            function="test_logger_enrichment",
            level="info",
            message_template="user authenticated",
            line=60,
            lexical_parents=["AuthService"],
            call_parents=["run_auth"],
            call_children=["db_query"],
            call_parent_names=["run_authentication"],
            call_child_names=["query_database"],
            signature=FunctionSignature(
                parameters=[
                    Parameter(name="user", type_hint="str", default=None)
                ],
                return_type="None",
                is_async=False,
                decorators=[]
            )
        )
    }
    graph = LogLoomGraph(project="test-proj", built_at="2026", nodes=nodes)
    
    monkeypatch.setattr("logloom.logger.wrapper.load_graph", lambda: graph)
    
    mock_structlog = MagicMock()
    monkeypatch.setattr(structlog, "get_logger", lambda name: mock_structlog)
    
    logger = get_logger("auth_service")
    assert logger.graph is not None
    assert logger.resolver is not None
    
    logger.info("user authenticated", user="alice")
    
    # Assert structlog was called with enrichment parameters
    mock_structlog.info.assert_called_once_with(
        "user authenticated", 
        user="alice", 
        **{
            "logloom.node_id": "ll:auth_ok",
            "logloom.traversal": ["AuthService"],
            "logloom.call_parents": ["run_auth"],
            "logloom.call_children": ["db_query"],
            "logloom.call_parent_names": ["run_authentication"],
            "logloom.call_child_names": ["query_database"],
            "logloom.signature": {
                "parameters": [{"name": "user", "type_hint": "str", "default": None}],
                "return_type": "None",
                "is_async": False,
                "decorators": []
            }
        }
    )
