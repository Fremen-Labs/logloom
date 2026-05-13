"""Tests for Issue #24 — TypeScript/JavaScript Tree-sitter scanner.

Comprehensive tests covering: console.*, winston, pino, class methods,
arrow functions, async/await, template literals, string concatenation,
try/catch detection, retry loops, default exports.
"""

import pytest
from pathlib import Path
from logloom.scanner.ts_scanner import TypeScriptScanner

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SAMPLE_TS = FIXTURES_DIR / "sample_app.ts"


@pytest.fixture
def ts_scanner():
    scanner = TypeScriptScanner()
    if not scanner.available:
        pytest.skip("tree-sitter-typescript/javascript not installed")
    return scanner


# ── Fixture-based tests ───────────────────────────────────────────────────────

def test_ts_scanner_fixture_coverage(ts_scanner):
    """Scan the real fixture and verify all expected patterns are found."""
    sites = ts_scanner.scan_file(SAMPLE_TS)

    assert len(sites) >= 28, f"Expected >=28 sites, found {len(sites)}"

    funcs = {s.function_name for s in sites}
    levels = {s.log_level for s in sites}

    # Functions from all patterns should be found
    expected_funcs = {
        "handleLogin",
        "processPayment",
        "fetchData",
        "shutdown",
        "retryOperation",
    }
    missing = expected_funcs - funcs
    assert not missing, f"Missing functions: {missing}"

    # Class methods should include class-qualified names
    class_sites = [s for s in sites if s.class_name == "UserService"]
    assert len(class_sites) >= 4, f"Expected >=4 UserService sites, found {len(class_sites)}"

    # All log levels should be represented
    assert "debug" in levels
    assert "info" in levels
    assert "warning" in levels
    assert "error" in levels
    assert "critical" in levels


def test_ts_scanner_class_method_qualification(ts_scanner):
    """Class methods should be qualified: UserService.createUser."""
    sites = ts_scanner.scan_file(SAMPLE_TS)

    user_service_sites = [s for s in sites if s.class_name == "UserService"]
    func_names = {s.function_name for s in user_service_sites}

    assert any("createUser" in fn for fn in func_names)
    assert any("deleteUser" in fn for fn in func_names)


def test_ts_scanner_arrow_function_resolution(ts_scanner):
    """Arrow functions should be resolved to their variable names."""
    sites = ts_scanner.scan_file(SAMPLE_TS)

    payment_sites = [s for s in sites if "processPayment" in (s.function_name or "")]
    assert len(payment_sites) >= 3, f"Expected >=3 processPayment sites, found {len(payment_sites)}"


def test_ts_scanner_template_literal_normalization(ts_scanner):
    """Template literal interpolation ${...} should be normalized to {}."""
    sites = ts_scanner.scan_file(SAMPLE_TS)

    template_sites = [s for s in sites if "{}" in s.message_template]
    assert len(template_sites) >= 3, f"Expected >=3 template-normalized sites, found {len(template_sites)}"

    # No raw ${...} should remain
    for s in sites:
        assert "${" not in s.message_template, \
            f"Raw interpolation found: {s.message_template}"


# ── Inline pattern tests ──────────────────────────────────────────────────────

def test_ts_scanner_javascript(ts_scanner, tmp_path: Path):
    """Scanner should handle .js files."""
    f = tmp_path / "app.js"
    f.write_text('''
const winston = require('winston');
const logger = winston.createLogger({ level: 'info' });

function startup() {
    console.log("App starting");
    logger.info("Loading config");
}

function shutdown() {
    console.warn("Shutting down");
}
''')
    sites = ts_scanner.scan_file(f)
    assert len(sites) >= 3
    funcs = {s.function_name for s in sites}
    assert "startup" in funcs
    assert "shutdown" in funcs


def test_ts_scanner_try_catch_detection(ts_scanner, tmp_path: Path):
    """Log calls inside try/catch should have in_try_except context."""
    f = tmp_path / "trycatch.ts"
    f.write_text('''
function riskyOp(): void {
    try {
        console.log("Attempting operation");
    } catch (e) {
        console.error("Operation failed");
    }
}
''')
    sites = ts_scanner.scan_file(f)
    assert len(sites) == 2

    # At least one should be in a try/catch
    try_sites = [s for s in sites if s.lexical_context.get("in_try_except")]
    assert len(try_sites) >= 1


def test_ts_scanner_skips_non_ts(ts_scanner, tmp_path: Path):
    """Non-TS/JS files should be silently skipped."""
    f = tmp_path / "notts.py"
    f.write_text("print('hello')")
    assert ts_scanner.scan_file(f) == []


def test_ts_scanner_empty_file(ts_scanner, tmp_path: Path):
    """Empty TS files should return no sites."""
    f = tmp_path / "empty.ts"
    f.write_text("")
    assert ts_scanner.scan_file(f) == []


def test_ts_scanner_mjs_extension(ts_scanner, tmp_path: Path):
    """ESM .mjs files should be scanned."""
    f = tmp_path / "module.mjs"
    f.write_text('''
export function init() {
    console.log("ESM module initialized");
}
''')
    sites = ts_scanner.scan_file(f)
    assert len(sites) == 1
    assert sites[0].function_name == "init"
