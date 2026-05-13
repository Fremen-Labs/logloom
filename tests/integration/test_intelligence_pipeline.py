"""Integration tests for Milestone 2: Intelligence pipeline.

Tests the full build pipeline with tags, call-graph, and git enabled.
Also tests the call-graph edge resolver in isolation.
"""

import pytest
from pathlib import Path
from logloom.graph.builder import GraphBuilder
from logloom.intelligence.call_graph import CallGraphResolver
from logloom.intelligence.tagger import infer_tags


# ── Fixture: a multi-function app with inter-function calls ───────────────────

MULTI_FUNC_APP = '''
import logging

logger = logging.getLogger(__name__)


def validate_input(data):
    """Validates incoming data."""
    logger.debug("Validating input data")
    if not data:
        logger.error("Empty input received")
        return False
    return True


def process_order(order_id):
    """Processes an order — calls validate_input."""
    logger.info(f"Processing order {order_id}")
    if not validate_input(order_id):
        logger.warning("Order validation failed")
        return
    charge_payment(order_id)
    logger.info("Order processed successfully")


def charge_payment(order_id):
    """Charges payment — called by process_order."""
    try:
        logger.info(f"Charging payment for order {order_id}")
    except Exception:
        logger.exception("Payment charge failed")
'''


def test_full_intelligence_pipeline(tmp_path: Path):
    """End-to-end: build with tags + call-graph + git."""
    app_file = tmp_path / "orders.py"
    app_file.write_text(MULTI_FUNC_APP)

    builder = GraphBuilder()
    graph = builder.build(
        [app_file],
        project_name="test-orders",
        enable_tags=True,
        enable_call_graph=True,
        enable_git=True,
    )

    # Should have found all 7 log sites
    assert len(graph.nodes) == 7

    # ── Verify semantic tags ──────────────────────────────────────────────
    node_by_msg = {n.message_template: n for n in graph.nodes.values()}

    # "Validating input data" in validate_input → should get "validation" tag
    validate_node = node_by_msg.get("Validating input data")
    assert validate_node is not None
    assert "validation" in validate_node.semantic_tags
    assert "debug" in validate_node.semantic_tags  # level-based tag

    # "Payment charge failed" at exception level → should get "error" tag
    fail_node = node_by_msg.get("Payment charge failed")
    assert fail_node is not None
    assert "error" in fail_node.semantic_tags
    assert "payment" in fail_node.semantic_tags  # from function name

    # "Charging payment for order {}" → should get "payment" tag
    charge_node = node_by_msg.get("Charging payment for order {}")
    assert charge_node is not None
    assert "payment" in charge_node.semantic_tags

    # ── Verify git metadata ───────────────────────────────────────────────
    assert graph.commit_sha is not None
    assert graph.branch is not None


def test_call_graph_edges(tmp_path: Path):
    """Verify inter-function call-graph edge resolution."""
    app_file = tmp_path / "orders.py"
    app_file.write_text(MULTI_FUNC_APP)

    # Build a base graph without call-graph
    builder = GraphBuilder()
    graph = builder.build(
        [app_file],
        enable_tags=False,
        enable_call_graph=False,
        enable_git=False,
    )

    # Now resolve call-graph edges
    resolver = CallGraphResolver()
    enriched = resolver.resolve(graph, [app_file])

    node_by_func = {}
    for n in enriched.nodes.values():
        node_by_func.setdefault(n.function, []).append(n)

    # process_order calls validate_input and charge_payment
    # So nodes in validate_input should have call_parents pointing to process_order nodes
    validate_nodes = node_by_func.get("validate_input", [])
    process_nodes = node_by_func.get("process_order", [])
    charge_nodes = node_by_func.get("charge_payment", [])

    assert len(validate_nodes) > 0
    assert len(process_nodes) > 0
    assert len(charge_nodes) > 0

    # validate_input nodes should have at least one call_parent from process_order
    process_node_ids = {n.node_id for n in process_nodes}
    for vn in validate_nodes:
        parent_overlap = set(vn.call_parents) & process_node_ids
        assert len(parent_overlap) > 0, (
            f"validate_input node {vn.node_id} should have process_order as a call_parent"
        )

    # process_order nodes should have call_children pointing to validate_input + charge_payment
    validate_ids = {n.node_id for n in validate_nodes}
    charge_ids = {n.node_id for n in charge_nodes}
    for pn in process_nodes:
        child_set = set(pn.call_children)
        assert child_set & validate_ids, "process_order should have validate_input as call_child"
        assert child_set & charge_ids, "process_order should have charge_payment as call_child"


def test_redaction_with_tags(tmp_path: Path):
    """Redaction should still work alongside the intelligence passes."""
    app_file = tmp_path / "secrets.py"
    app_file.write_text('''
import logging
logger = logging.getLogger(__name__)

def login():
    logger.info("User password is hunter2")
    logger.debug("Token refreshed")
''')

    builder = GraphBuilder()
    graph = builder.build(
        [app_file],
        redact_patterns=["password"],
        enable_tags=True,
        enable_call_graph=False,
        enable_git=False,
    )

    messages = {n.message_template for n in graph.nodes.values()}
    assert "[REDACTED]" in messages
    assert "Token refreshed" in messages

    # The redacted node should still get tags from the function name
    for n in graph.nodes.values():
        if n.message_template == "[REDACTED]":
            assert "auth" in n.semantic_tags  # from "login" function name
