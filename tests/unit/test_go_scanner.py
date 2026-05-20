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


# ── Production hardening tests ────────────────────────────────────────────────

def test_go_scanner_zap_field_constructor_excluded(go_scanner, tmp_path: Path):
    """zap.Error(err) should NOT be captured as a log call; only logger.Error() should."""
    f = tmp_path / "zap_field.go"
    f.write_text('''
package main
import (
    "fmt"
    "go.uber.org/zap"
)
func zapField(logger *zap.Logger) {
    logger.Error("operation failed", zap.Error(fmt.Errorf("timeout")))
    logger.Info("user created", zap.String("uid", "u-123"))
}
''')
    sites = go_scanner.scan_file(f)
    assert len(sites) == 2

    msgs = {s.message_template for s in sites}
    assert "operation failed" in msgs, f"Expected 'operation failed', got {msgs}"
    assert "user created" in msgs
    # zap.Error's "timeout" and zap.String's "uid" should NOT appear
    assert "timeout" not in msgs
    assert "uid" not in msgs


def test_go_scanner_string_concatenation(go_scanner, tmp_path: Path):
    """String concatenation (binary_expression +) should be flattened."""
    f = tmp_path / "concat.go"
    f.write_text('''
package main
import "log"
func concat() {
    log.Println("prefix: " + someVar + " suffix")
}
''')
    sites = go_scanner.scan_file(f)
    assert len(sites) == 1
    assert sites[0].message_template == "prefix: {} suffix"


def test_go_scanner_multiline_concat(go_scanner, tmp_path: Path):
    """Multi-line string concatenation should be joined into a single message."""
    f = tmp_path / "multiline.go"
    f.write_text('''
package main
import "log/slog"
func multi() {
    slog.Info("this is a long " +
        "message that spans " +
        "multiple lines")
}
''')
    sites = go_scanner.scan_file(f)
    assert len(sites) == 1
    assert sites[0].message_template == "this is a long message that spans multiple lines"


def test_go_scanner_switch_context(go_scanner, tmp_path: Path):
    """Log calls inside switch/case should have in_switch context."""
    f = tmp_path / "switch.go"
    f.write_text('''
package main
import "log/slog"
func sw(level string) {
    switch level {
    case "debug":
        slog.Debug("debug level")
    case "info":
        slog.Info("info level")
    default:
        slog.Warn("unknown level")
    }
}
''')
    sites = go_scanner.scan_file(f)
    assert len(sites) == 3
    for s in sites:
        assert s.lexical_context.get("in_switch"), \
            f"L{s.line} should have in_switch=True"


def test_go_scanner_closure_context(go_scanner, tmp_path: Path):
    """Anonymous closures should detect in_closure and inherit outer function name."""
    f = tmp_path / "closure.go"
    f.write_text('''
package main
import "log"
func outer() {
    handler := func() {
        log.Println("inside closure")
    }
    handler()
    go func() {
        log.Println("goroutine closure")
    }()
}
''')
    sites = go_scanner.scan_file(f)
    assert len(sites) >= 2

    # The goroutine one should have both in_goroutine and in_closure
    goroutine_sites = [s for s in sites if s.lexical_context.get("in_goroutine")]
    assert len(goroutine_sites) >= 1

    # All sites should resolve to the outer function or the assigned var name
    for s in sites:
        assert s.function_name != "<module>", \
            f"Expected named function, got <module> at L{s.line}"


def test_go_scanner_fmt_sprintf_extraction(go_scanner, tmp_path: Path):
    """fmt.Sprintf/fmt.Errorf as log arguments should have their format string extracted."""
    f = tmp_path / "sprintf.go"
    f.write_text('''
package main
import (
    "log"
    "fmt"
    "github.com/sirupsen/logrus"
)
func fmtCases() {
    log.Println(fmt.Sprintf("processed %d records in %v", count, elapsed))
    logrus.Error(fmt.Errorf("connection to %s failed", host))
}
''')
    sites = go_scanner.scan_file(f)
    assert len(sites) == 2

    msgs = [s.message_template for s in sites]
    assert "processed {} records in {}" in msgs
    assert "connection to {} failed" in msgs


def test_go_scanner_function_signatures(go_scanner, tmp_path: Path):
    """Go scanner should extract function signatures including return types and parameters."""
    f = tmp_path / "signature.go"
    f.write_text('''
package main
import "log"
func processOrder(orderID string, amount float64) (bool, error) {
    log.Println("Processing order")
    return true, nil
}
''')
    sites = go_scanner.scan_file(f)
    assert len(sites) == 1
    site = sites[0]
    assert site.signature is not None
    assert site.signature["is_async"] is False
    assert site.signature["return_type"] == "(bool, error)"
    assert len(site.signature["parameters"]) == 2
    assert site.signature["parameters"][0]["name"] == "orderID"
    assert site.signature["parameters"][0]["type_hint"] == "string"
    assert site.signature["parameters"][1]["name"] == "amount"
    assert site.signature["parameters"][1]["type_hint"] == "float64"


