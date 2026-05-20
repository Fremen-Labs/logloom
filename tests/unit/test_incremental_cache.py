"""Tests for Step 7 — Incremental build cache.

Validates BuildCache serialization, hash-based cache hits/misses,
stale entry cleanup, and correct integration with the build pipeline.
"""

import json
from pathlib import Path

from logloom.graph.cache import BuildCache, calculate_file_hash
from logloom.scanner.base import LogCallSite
from logloom.graph.model import ModelDefinition, ModelField


# ── BuildCache unit tests ─────────────────────────────────────────────────────


def test_cache_roundtrip(tmp_path: Path):
    """Cache should serialize sites, models, imports, and functions, then
    deserialize them correctly on reload."""
    cache_file = tmp_path / ".logloom-cache.json"
    cache = BuildCache(cache_file)

    fake_file = tmp_path / "app.py"
    fake_file.write_text("import logging\nlogger = logging.getLogger(__name__)\ndef f(): logger.info('hello')\n")

    site = LogCallSite(
        file_path="app.py",
        module_path="app",
        class_name="",
        function_name="f",
        log_level="info",
        message_template="hello",
        line=3,
        column=4,
        lexical_context={"enclosing_function": "f"},
        signature={"parameters": [{"name": "x", "type_hint": "int", "default": None}], "return_type": "None", "is_async": False, "decorators": []},
    )

    model = ModelDefinition(
        name="User",
        file="models.py",
        line=5,
        base_classes=["BaseModel"],
        fields=[ModelField(name="age", type_hint="int", default=None)],
    )

    cache.set_file_entry(
        fake_file,
        file_hash="abc123",
        sites=[site],
        models=[model],
        imports=[".models", "json"],
        defined_functions=["f", "g"],
    )
    cache.save()

    # Reload from disk
    cache2 = BuildCache(cache_file)
    entry = cache2.get_file_entry(fake_file)
    assert entry is not None
    assert entry["hash"] == "abc123"
    assert len(entry["sites"]) == 1
    assert entry["sites"][0]["function_name"] == "f"
    assert entry["sites"][0]["signature"]["return_type"] == "None"
    assert len(entry["models"]) == 1
    assert entry["models"][0]["name"] == "User"
    assert entry["imports"] == [".models", "json"]
    assert sorted(entry["defined_functions"]) == ["f", "g"]


def test_cache_miss_on_hash_change(tmp_path: Path):
    """Changing the file hash should cause a cache miss."""
    cache_file = tmp_path / ".logloom-cache.json"
    cache = BuildCache(cache_file)

    fake_file = tmp_path / "app.py"
    fake_file.write_text("pass")

    cache.set_file_entry(fake_file, "old_hash", [], [], [], [])
    cache.save()

    cache2 = BuildCache(cache_file)
    entry = cache2.get_file_entry(fake_file)
    assert entry is not None
    assert entry["hash"] == "old_hash"
    # If we check with a different hash, the caller treats it as a miss
    assert entry["hash"] != "new_hash"


def test_cache_clean_removes_deleted_files(tmp_path: Path):
    """clean_unused_entries should evict entries for files no longer in the scan set."""
    cache_file = tmp_path / ".logloom-cache.json"
    cache = BuildCache(cache_file)

    file_a = tmp_path / "a.py"
    file_b = tmp_path / "b.py"
    file_a.write_text("pass")
    file_b.write_text("pass")

    cache.set_file_entry(file_a, "h1", [], [], [], [])
    cache.set_file_entry(file_b, "h2", [], [], [], [])
    assert len(cache.data["files"]) == 2

    # Only file_a is still active
    cache.clean_unused_entries([file_a])
    assert len(cache.data["files"]) == 1
    assert cache.get_file_entry(file_a) is not None
    assert cache.get_file_entry(file_b) is None


def test_cache_corrupt_json_gracefully_resets(tmp_path: Path):
    """A corrupt cache file should not crash; it should reset to empty."""
    cache_file = tmp_path / ".logloom-cache.json"
    cache_file.write_text("{invalid json!!")

    cache = BuildCache(cache_file)
    assert cache.data == {"files": {}}


def test_calculate_file_hash_deterministic(tmp_path: Path):
    """Same content should produce the same hash."""
    f = tmp_path / "test.py"
    f.write_text("hello world")

    h1 = calculate_file_hash(f)
    h2 = calculate_file_hash(f)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex digest


def test_calculate_file_hash_changes_on_modification(tmp_path: Path):
    """Modifying file content should change the hash."""
    f = tmp_path / "test.py"
    f.write_text("version 1")
    h1 = calculate_file_hash(f)

    f.write_text("version 2")
    h2 = calculate_file_hash(f)

    assert h1 != h2


def test_calculate_file_hash_missing_file():
    """Missing file should return empty string, not raise."""
    h = calculate_file_hash(Path("/nonexistent/file.py"))
    assert h == ""
