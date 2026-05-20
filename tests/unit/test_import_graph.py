"""Tests for Phase E: Import Graph."""

import pytest
from pathlib import Path
from logloom.intelligence.import_graph import (
    compute_imports,
    _extract_python_imports,
    _extract_go_imports,
    _extract_ts_imports,
)


def test_extract_python_imports(tmp_path):
    py_code = """
import sys, os
from pydantic import BaseModel
from .models import User
import numpy as np
"""
    f = tmp_path / "app.py"
    f.write_text(py_code, encoding="utf-8")

    imports = _extract_python_imports(f)
    # Expected: sys, os, pydantic, .models, numpy
    assert "sys" in imports
    assert "os" in imports
    assert "pydantic" in imports
    assert ".models" in imports
    assert "numpy" in imports
    assert len(imports) == 5


def test_extract_go_imports(tmp_path):
    go_code = """
package main
import "fmt"
import (
	"os"
	"path/filepath"
)
"""
    f = tmp_path / "main.go"
    f.write_text(go_code, encoding="utf-8")

    imports = _extract_go_imports(f)
    assert "fmt" in imports
    assert "os" in imports
    assert "path/filepath" in imports
    assert len(imports) == 3


def test_extract_ts_imports(tmp_path):
    ts_code = """
import { Task } from "./models";
import * as fs from "fs";
const express = require("express");
import("./lazy");
"""
    f = tmp_path / "main.ts"
    f.write_text(ts_code, encoding="utf-8")

    imports = _extract_ts_imports(f)
    assert "./models" in imports
    assert "fs" in imports
    assert "express" in imports
    assert "./lazy" in imports
    assert len(imports) == 4


def test_compute_imports_e2e(tmp_path):
    # Setup subdirectories to simulate projects
    py_dir = tmp_path / "src" / "py"
    py_dir.mkdir(parents=True)
    py_code = "import json\nfrom .models import local_mod"
    (py_dir / "app.py").write_text(py_code, encoding="utf-8")
    (py_dir / "models.py").write_text("", encoding="utf-8")

    go_dir = tmp_path / "go"
    go_dir.mkdir()
    go_code = 'package main\nimport "strings"'
    (go_dir / "main.go").write_text(go_code, encoding="utf-8")

    # With external imports included
    imports_graph_all = compute_imports([tmp_path], ["python", "go"], include_external=True)
    
    assert "py.app" in imports_graph_all
    assert "json" in imports_graph_all["py.app"]
    assert ".models" in imports_graph_all["py.app"]

    # Go module name should map to the relative path/file path without extension
    matched_key_all = next((k for k in imports_graph_all if k.endswith("go/main")), None)
    assert matched_key_all is not None
    assert imports_graph_all[matched_key_all] == ["strings"]

    # With default (only internal imports)
    imports_graph_internal = compute_imports([tmp_path], ["python", "go"])
    
    assert "py.app" in imports_graph_internal
    # json is filtered out, but local_mod should resolve to py.models and be kept
    assert "json" not in imports_graph_internal["py.app"]
    assert "py.models" in imports_graph_internal["py.app"]

    matched_key_internal = next((k for k in imports_graph_internal if k.endswith("go/main")), None)
    assert matched_key_internal is not None
    # strings is external stdlib, so it should be filtered out
    assert imports_graph_internal[matched_key_internal] == []
