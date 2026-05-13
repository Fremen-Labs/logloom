"""Tests for Issue #23 — Go Tree-sitter scanner.

Comprehensive tests covering: stdlib log, slog, zap (typed + sugar),
logrus (with WithFields chaining), zerolog (builder chain), method receivers,
deferred functions, complex control flow, format verb normalization.
"""

import pytest
from pathlib import Path
from logloom.scanner.go_scanner import GoScanner

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SAMPLE_GO = FIXTURES_DIR / "sample_app.go"


@pytest.fixture
def go_scanner():
    scanner = GoScanner()
    if not scanner.available:
        pytest.skip("tree-sitter-go not installed")
    return scanner


# ── Fixture-based tests ───────────────────────────────────────────────────────

def test_go_scanner_fixture_coverage(go_scanner):
    """Scan the real fixture and verify all expected patterns are found."""
    sites = go_scanner.scan_file(SAMPLE_GO)

    # We expect a healthy number of sites across all frameworks
    assert len(sites) >= 28, f"Expected >=28 sites, found {len(sites)}"

    funcs = {s.function_name for s in sites}
    levels = {s.log_level for s in sites}

    # Functions from all frameworks should be found
    expected_funcs = {
        "startServer",
        "shutdownServer",
        "handleRequest",
        "processRequest",
        "zapTypedExample",
        "zapSugarExample",
        "logrusExamples",
        "zerologExamples",
        "riskyOperation",
        "retryWithBackoff",
        "main",
    }
    missing = expected_funcs - funcs
    assert not missing, f"Missing functions: {missing}"

    # All log levels should be represented
    assert "debug" in levels
    assert "info" in levels
    assert "warning" in levels
    assert "error" in levels
    assert "critical" in levels


def test_go_scanner_zerolog_levels(go_scanner):
    """Zerolog chain level resolution: log.Error().Msg() should resolve to 'error'."""
    sites = go_scanner.scan_file(SAMPLE_GO)

    zerolog_sites = [s for s in sites if s.function_name == "zerologExamples"]
    assert len(zerolog_sites) >= 4, f"Expected >=4 zerolog sites, found {len(zerolog_sites)}"

    # Build a map of message → level for zerolog sites
    msg_level = {s.message_template: s.log_level for s in zerolog_sites}

    assert msg_level.get("Server started successfully") == "info"
    assert msg_level.get("Request processing failed") == "error"
    assert msg_level.get("Cache lookup") == "debug"
    assert msg_level.get("Retrying operation") == "warning"


def test_go_scanner_method_receiver(go_scanner):
    """Method receivers should be qualified: AuthService.Authenticate."""
    sites = go_scanner.scan_file(SAMPLE_GO)

    auth_sites = [s for s in sites if "Authenticate" in s.function_name]
    assert len(auth_sites) >= 2, f"Expected >=2 auth sites, found {len(auth_sites)}"

    # The function name should include the receiver type
    func_names = {s.function_name for s in auth_sites}
    assert any("AuthService" in fn for fn in func_names), \
        f"Expected receiver-qualified name, got: {func_names}"


# ── Inline pattern tests ──────────────────────────────────────────────────────

def test_go_scanner_format_verb_normalization(go_scanner, tmp_path: Path):
    """Go format verbs (%s, %d, %v, etc.) should be normalized to {}."""
    f = tmp_path / "fmt.go"
    f.write_text('''
package main
import "log"
func foo() {
    log.Printf("User %s logged in from %s at %d", username, ip, time)
    log.Printf("Ratio: %.2f, hex: %x, quoted: %q", r, h, q)
}
''')
    sites = go_scanner.scan_file(f)
    assert len(sites) == 2
    assert "{}" in sites[0].message_template
    assert "%s" not in sites[0].message_template
    assert "%d" not in sites[0].message_template
    assert "{}" in sites[1].message_template


def test_go_scanner_raw_string_literal(go_scanner, tmp_path: Path):
    """Raw string literals (backtick) should be handled."""
    f = tmp_path / "raw.go"
    f.write_text('''
package main
import "log"
func bar() {
    log.Println(`This is a raw string message`)
}
''')
    sites = go_scanner.scan_file(f)
    assert len(sites) == 1
    assert "raw string message" in sites[0].message_template


def test_go_scanner_skips_non_go(go_scanner, tmp_path: Path):
    """Non-Go files should be silently skipped."""
    f = tmp_path / "notgo.py"
    f.write_text("print('hello')")
    assert go_scanner.scan_file(f) == []


def test_go_scanner_empty_file(go_scanner, tmp_path: Path):
    """Empty Go files should return no sites."""
    f = tmp_path / "empty.go"
    f.write_text("package main\n")
    assert go_scanner.scan_file(f) == []


def test_go_scanner_complex_control_flow(go_scanner, tmp_path: Path):
    """Log calls inside loops, conditionals, and goroutines should be detected."""
    f = tmp_path / "flow.go"
    f.write_text('''
package main
import "log"
func worker(jobs <-chan int) {
    for j := range jobs {
        if j%2 == 0 {
            log.Printf("Processing even job %d", j)
        }
        go func() {
            log.Println("Goroutine processing")
        }()
    }
}
''')
    sites = go_scanner.scan_file(f)
    assert len(sites) >= 2

    # At least one should be in a loop
    loop_sites = [s for s in sites if s.lexical_context.get("in_loop")]
    assert len(loop_sites) >= 1
