"""Tests for Issue #23 — Go Tree-sitter scanner."""

import pytest
from pathlib import Path
from logloom.scanner.go_scanner import GoScanner


@pytest.fixture
def go_scanner():
    scanner = GoScanner()
    if not scanner.available:
        pytest.skip("tree-sitter-go not installed")
    return scanner


GO_SAMPLE = '''
package main

import (
	"log"
	"log/slog"
	"fmt"
)

func main() {
	log.Printf("Starting server on port %d", 8080)
	slog.Info("Server ready", "addr", ":8080")
}

func handleRequest(w http.ResponseWriter, r *http.Request) {
	slog.Debug("Handling request", "method", r.Method)
	if r.Method == "POST" {
		slog.Warn("Deprecated endpoint called")
	}
	log.Fatalf("Critical failure in %s", r.URL.Path)
}

func processOrder(orderID string) error {
	log.Printf("Processing order %s", orderID)
	slog.Error("Order processing failed", "order_id", orderID)
	return nil
}
'''


def test_go_scanner_basic(go_scanner, tmp_path: Path):
    f = tmp_path / "main.go"
    f.write_text(GO_SAMPLE)

    sites = go_scanner.scan_file(f)
    assert len(sites) >= 5

    levels = {s.log_level for s in sites}
    assert "info" in levels
    assert "debug" in levels
    assert "warning" in levels
    assert "critical" in levels

    # Verify function context
    funcs = {s.function_name for s in sites}
    assert "main" in funcs
    assert "handleRequest" in funcs
    assert "processOrder" in funcs


def test_go_scanner_format_string(go_scanner, tmp_path: Path):
    f = tmp_path / "fmt.go"
    f.write_text('''
package main
import "log"
func foo() {
    log.Printf("User %s logged in from %s", username, ip)
}
''')
    sites = go_scanner.scan_file(f)
    assert len(sites) == 1
    # %s should be replaced with {}
    assert "{}" in sites[0].message_template


def test_go_scanner_skips_non_go(go_scanner, tmp_path: Path):
    f = tmp_path / "notgo.py"
    f.write_text("print('hello')")
    assert go_scanner.scan_file(f) == []
