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


# ── Go call-graph edge resolution tests (Phase 4d) ───────────────────────────

GO_COBRA_APP = '''
package cmd

import (
    "fmt"
    "log"
    "log/slog"

    "github.com/spf13/cobra"
)

func validateManifest(path string) error {
    slog.Info("Validating manifest", "path", path)
    return nil
}

func executeSecurityScan(target string) {
    slog.Info("Running security scan", "target", target)
}

var scanCmd = &cobra.Command{
    Use: "scan",
    RunE: func(cmd *cobra.Command, args []string) error {
        slog.Info("Starting scan command")
        if err := validateManifest("release.yaml"); err != nil {
            return err
        }
        executeSecurityScan("my-image:latest")
        return nil
    },
}

func setupServer() {
    defer func() {
        slog.Info("Server cleanup complete")
        if r := recover(); r != nil {
            log.Printf("Recovered from panic: %v", r)
        }
    }()
    slog.Info("Starting server setup")
    executeSecurityScan("server-image")
}

func orchestrate() {
    action := func() error {
        slog.Info("Executing orchestration action")
        validateManifest("config.yaml")
        return nil
    }
    _ = action()
    slog.Info("Orchestration complete")
}

func init() {
    log.Println("Initializing scan command")
}
'''


def test_go_cobra_struct_field_closure_edges(tmp_path: Path):
    """Cobra RunE: func(){} struct field closures should produce call-graph edges.

    The RunE closure calls validateManifest and executeSecurityScan.
    Nodes in those functions should have call_parents, and the closure's
    log nodes should have call_children.
    """
    app_file = tmp_path / "scan.go"
    app_file.write_text(GO_COBRA_APP)

    builder = GraphBuilder()
    graph = builder.build(
        [app_file],
        project_name="test-cobra",
        enable_tags=False,
        enable_call_graph=True,
        enable_git=False,
        languages=["go"],
    )

    assert len(graph.nodes) > 0, "Should find Go log nodes"

    # Count nodes with edges
    nodes_with_edges = sum(
        1 for n in graph.nodes.values()
        if n.call_parents or n.call_children
    )
    total = len(graph.nodes)
    pct = (nodes_with_edges / total * 100) if total else 0

    # The RunE closure should produce edges
    assert nodes_with_edges > 0, (
        f"Expected some nodes with call-graph edges, got 0/{total}"
    )

    # Validate specific edges: validateManifest should have parents
    validate_nodes = [
        n for n in graph.nodes.values()
        if n.function == "validateManifest"
    ]
    # validateManifest is called from RunE closure AND orchestrate closure
    for vn in validate_nodes:
        assert len(vn.call_parents) > 0, (
            f"validateManifest node should have call_parents from closures"
        )


def test_go_defer_closure_edges(tmp_path: Path):
    """defer func() { body }() should walk the closure body for edges."""
    app_file = tmp_path / "defer.go"
    app_file.write_text(GO_COBRA_APP)

    builder = GraphBuilder()
    graph = builder.build(
        [app_file],
        enable_tags=False,
        enable_call_graph=True,
        enable_git=False,
        languages=["go"],
    )

    # setupServer has a defer closure. The log inside the defer should
    # be attributed to setupServer. setupServer also calls executeSecurityScan,
    # so its nodes should have call_children.
    setup_nodes = [
        n for n in graph.nodes.values()
        if n.function == "setupServer"
    ]
    assert len(setup_nodes) > 0, "Should find setupServer log nodes"

    # At least one setupServer node should have call_children
    # (because setupServer calls executeSecurityScan)
    has_children = any(len(n.call_children) > 0 for n in setup_nodes)
    assert has_children, (
        "setupServer should have call_children pointing to executeSecurityScan"
    )


def test_go_var_assigned_closure_edges(tmp_path: Path):
    """handler := func() { calls... } should inline calls into enclosing function."""
    app_file = tmp_path / "var_closure.go"
    app_file.write_text(GO_COBRA_APP)

    builder = GraphBuilder()
    graph = builder.build(
        [app_file],
        enable_tags=False,
        enable_call_graph=True,
        enable_git=False,
        languages=["go"],
    )

    # orchestrate has a var-assigned closure (action := func(){...}).
    # The closure calls validateManifest, so orchestrate should have
    # call_children pointing to validateManifest.
    orch_nodes = [
        n for n in graph.nodes.values()
        if n.function == "orchestrate"
    ]
    assert len(orch_nodes) > 0, "Should find orchestrate log nodes"

    has_children = any(len(n.call_children) > 0 for n in orch_nodes)
    assert has_children, (
        "orchestrate should have call_children from var-assigned closure"
    )


def test_go_call_graph_edge_coverage_minimum(tmp_path: Path):
    """Overall Go call-graph edge coverage should exceed 60% on a realistic app."""
    app_file = tmp_path / "app.go"
    app_file.write_text(GO_COBRA_APP)

    builder = GraphBuilder()
    graph = builder.build(
        [app_file],
        enable_tags=False,
        enable_call_graph=True,
        enable_git=False,
        languages=["go"],
    )

    total = len(graph.nodes)
    assert total > 0

    nodes_with_edges = sum(
        1 for n in graph.nodes.values()
        if n.call_parents or n.call_children
    )
    pct = nodes_with_edges / total * 100

    # With defer, var-closure, and struct-field improvements,
    # we should be well above the old 66% baseline
    assert pct >= 60, (
        f"Expected >=60% edge coverage, got {pct:.0f}% ({nodes_with_edges}/{total})"
    )

