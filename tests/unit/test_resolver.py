"""Tests for the three-tier NodeResolver.

Tests cover:
  - Tier 1: Exact match on (module, function, message)
  - Tier 2: Fuzzy match on (function, message) — module mismatch
  - Tier 3: Template-aware regex match on formatted messages
  - Cache behavior for Tier 3
  - Edge cases: special regex characters in templates, empty messages
"""

import pytest

from logloom.logger.resolver import NodeResolver, _template_to_pattern
from logloom.graph.model import LogLoomGraph, GraphNode


@pytest.fixture
def graph_with_templates():
    """Graph containing both static and templated log messages."""
    return LogLoomGraph(
        project="test-resolver",
        built_at="2026-05-14T00:00:00Z",
        nodes={
            "ll:static_01": GraphNode(
                node_id="ll:static_01",
                file="app/service.py",
                module="app.service",
                function="connect",
                level="info",
                message_template="Successfully connected",
                line=10,
            ),
            "ll:template_01": GraphNode(
                node_id="ll:template_01",
                file="app/service.py",
                module="app.service",
                function="connect",
                level="info",
                message_template="Connecting to {} on port {}...",
                line=8,
            ),
            "ll:template_02": GraphNode(
                node_id="ll:template_02",
                file="app/service.py",
                module="app.service",
                function="connect",
                level="error",
                message_template="Connection failed: {}",
                line=15,
            ),
            "ll:template_03": GraphNode(
                node_id="ll:template_03",
                file="app/auth.py",
                module="app.auth",
                function="login",
                level="info",
                message_template="User '{}' logged in from {}",
                line=30,
            ),
            "ll:printf_01": GraphNode(
                node_id="ll:printf_01",
                file="app/metrics.py",
                module="app.metrics",
                function="report",
                level="info",
                message_template="Processed %d items in %.2f seconds",
                line=50,
            ),
            "ll:regex_chars": GraphNode(
                node_id="ll:regex_chars",
                file="app/parser.py",
                module="app.parser",
                function="parse",
                level="warning",
                message_template="Pattern [.*] matched {} times",
                line=22,
            ),
        },
    )


class TestTier1ExactMatch:
    """Tier 1: exact (module, function, message) lookups."""

    def test_exact_static_message(self, graph_with_templates):
        r = NodeResolver(graph_with_templates)
        assert r.resolve("app.service", "connect", "Successfully connected") == "ll:static_01"

    def test_exact_template_matches_raw_template_string(self, graph_with_templates):
        r = NodeResolver(graph_with_templates)
        # The raw template string still matches in Tier 1
        assert r.resolve("app.service", "connect", "Connecting to {} on port {}...") == "ll:template_01"

    def test_exact_miss(self, graph_with_templates):
        r = NodeResolver(graph_with_templates)
        assert r.resolve("app.service", "disconnect", "Something") is None


class TestTier2FuzzyMatch:
    """Tier 2: fuzzy (function, message) lookups with module mismatch."""

    def test_fuzzy_wrong_module(self, graph_with_templates):
        r = NodeResolver(graph_with_templates)
        # Wrong module but right function + message
        assert r.resolve("wrong.module", "connect", "Successfully connected") == "ll:static_01"

    def test_fuzzy_wrong_module_no_match_wrong_function(self, graph_with_templates):
        r = NodeResolver(graph_with_templates)
        assert r.resolve("wrong.module", "wrong_func", "Successfully connected") is None


class TestTier3TemplateMatch:
    """Tier 3: template-aware regex matching for formatted messages."""

    def test_python_format_single_placeholder(self, graph_with_templates):
        r = NodeResolver(graph_with_templates)
        result = r.resolve("app.service", "connect", "Connection failed: timeout after 30s")
        assert result == "ll:template_02"

    def test_python_format_multiple_placeholders(self, graph_with_templates):
        r = NodeResolver(graph_with_templates)
        result = r.resolve("app.service", "connect",
                          "Connecting to http://localhost on port 9200...")
        assert result == "ll:template_01"

    def test_python_format_with_quotes(self, graph_with_templates):
        r = NodeResolver(graph_with_templates)
        result = r.resolve("app.auth", "login",
                          "User 'admin' logged in from 192.168.1.1")
        assert result == "ll:template_03"

    def test_printf_format_placeholders(self, graph_with_templates):
        r = NodeResolver(graph_with_templates)
        result = r.resolve("app.metrics", "report",
                          "Processed 42 items in 1.23 seconds")
        assert result == "ll:printf_01"

    def test_template_with_regex_metacharacters(self, graph_with_templates):
        r = NodeResolver(graph_with_templates)
        # The template contains literal [.*] which must be escaped
        result = r.resolve("app.parser", "parse",
                          "Pattern [.*] matched 7 times")
        assert result == "ll:regex_chars"

    def test_template_miss_wrong_function(self, graph_with_templates):
        r = NodeResolver(graph_with_templates)
        # Right message format but wrong function — should NOT match
        result = r.resolve("app.service", "disconnect",
                          "Connection failed: something")
        assert result is None

    def test_template_miss_wrong_prefix(self, graph_with_templates):
        r = NodeResolver(graph_with_templates)
        # Message doesn't match the template prefix
        result = r.resolve("app.service", "connect",
                          "WRONG PREFIX: timeout after 30s")
        assert result is None

    def test_template_cache_hit(self, graph_with_templates):
        r = NodeResolver(graph_with_templates)
        # First call populates cache
        r.resolve("app.service", "connect", "Connection failed: error A")
        # Second call should hit cache
        result = r.resolve("app.service", "connect", "Connection failed: error A")
        assert result == "ll:template_02"

    def test_template_cache_stores_misses(self, graph_with_templates):
        r = NodeResolver(graph_with_templates)
        # Miss should be cached too
        r.resolve("app.service", "connect", "Some unknown message")
        assert ("connect", "Some unknown message") in r._template_cache
        assert r._template_cache[("connect", "Some unknown message")] is None


class TestTemplateToPattern:
    """Unit tests for the template→regex converter."""

    def test_static_returns_none(self):
        """Static templates (no placeholders) should return None."""
        assert _template_to_pattern("Successfully connected") is None

    def test_python_format_single(self):
        pat = _template_to_pattern("Error: {}")
        assert pat is not None
        assert pat.match("Error: something went wrong")
        assert not pat.match("Warning: something")

    def test_python_format_named(self):
        pat = _template_to_pattern("User {name} connected from {ip}")
        assert pat is not None
        assert pat.match("User admin connected from 10.0.0.1")

    def test_printf_format(self):
        pat = _template_to_pattern("Took %d ms to process %s")
        assert pat is not None
        assert pat.match("Took 42 ms to process request")

    def test_mixed_format(self):
        pat = _template_to_pattern("Batch {} completed in %d ms")
        assert pat is not None
        assert pat.match("Batch alpha-7 completed in 150 ms")

    def test_regex_metacharacters_escaped(self):
        """Ensure literal regex chars in templates are properly escaped."""
        pat = _template_to_pattern("Pattern (foo|bar) matched {} times")
        assert pat is not None
        assert pat.match("Pattern (foo|bar) matched 5 times")
        assert not pat.match("Pattern foobar matched 5 times")


class TestLegacyResolver:
    """Regression tests for existing behavior."""

    def test_basic_exact_and_fuzzy(self):
        """Original test_node_resolver behavior preserved."""
        graph = LogLoomGraph(
            project="test",
            built_at="2026",
            nodes={
                "ll:123": GraphNode(
                    node_id="ll:123",
                    file="a.py",
                    module="app.a",
                    function="do_a",
                    level="info",
                    message_template="Doing A",
                    line=10,
                )
            },
        )

        resolver = NodeResolver(graph)

        # Exact match
        assert resolver.resolve("app.a", "do_a", "Doing A") == "ll:123"

        # Fuzzy match (wrong module, right function/message)
        assert resolver.resolve("app.b", "do_a", "Doing A") == "ll:123"

        # No match
        assert resolver.resolve("app.a", "do_b", "Doing A") is None
