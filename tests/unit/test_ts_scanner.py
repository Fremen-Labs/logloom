"""Tests for Issue #24 — TypeScript/JavaScript Tree-sitter scanner."""

import pytest
from pathlib import Path
from logloom.scanner.ts_scanner import TypeScriptScanner


@pytest.fixture
def ts_scanner():
    scanner = TypeScriptScanner()
    if not scanner.available:
        pytest.skip("tree-sitter-typescript/javascript not installed")
    return scanner


TS_SAMPLE = '''
import { createLogger } from 'winston';

const logger = createLogger({ level: 'info' });

function handleLogin(username: string): void {
    console.log("Login attempt for user");
    logger.info("Authenticating user");
    if (!username) {
        console.error("Missing username");
    }
}

const processPayment = (orderId: string) => {
    logger.warn("Processing payment");
    try {
        console.debug(`Order ${orderId} charged`);
    } catch (e) {
        logger.error("Payment failed");
    }
};
'''

JS_SAMPLE = '''
const winston = require('winston');
const logger = winston.createLogger({ level: 'info' });

function startup() {
    console.log("App starting");
    logger.info("Loading config");
}

function shutdown() {
    console.warn("Shutting down");
}
'''


def test_ts_scanner_typescript(ts_scanner, tmp_path: Path):
    f = tmp_path / "app.ts"
    f.write_text(TS_SAMPLE)

    sites = ts_scanner.scan_file(f)
    assert len(sites) >= 4

    levels = {s.log_level for s in sites}
    assert "info" in levels
    assert "error" in levels

    funcs = {s.function_name for s in sites}
    assert "handleLogin" in funcs


def test_ts_scanner_javascript(ts_scanner, tmp_path: Path):
    f = tmp_path / "app.js"
    f.write_text(JS_SAMPLE)

    sites = ts_scanner.scan_file(f)
    assert len(sites) >= 3

    funcs = {s.function_name for s in sites}
    assert "startup" in funcs
    assert "shutdown" in funcs


def test_ts_scanner_template_literal(ts_scanner, tmp_path: Path):
    f = tmp_path / "tmpl.ts"
    f.write_text('''
function test() {
    console.log(`User ${username} logged in from ${ip}`);
}
''')
    sites = ts_scanner.scan_file(f)
    assert len(sites) == 1
    # Template literal interpolation should be generalized to {}
    assert "{}" in sites[0].message_template


def test_ts_scanner_skips_non_ts(ts_scanner, tmp_path: Path):
    f = tmp_path / "notts.py"
    f.write_text("print('hello')")
    assert ts_scanner.scan_file(f) == []
