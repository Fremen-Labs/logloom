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
    py_code = "import json"
    (py_dir / "app.py").write_text(py_code, encoding="utf-8")

    go_dir = tmp_path / "go"
    go_dir.mkdir()
    go_code = 'package main\nimport "strings"'
    (go_dir / "main.go").write_text(go_code, encoding="utf-8")

    imports_graph = compute_imports([tmp_path], ["python", "go"])
    
    # Python module name check:
    # Parts of tmp_path/src/py/app.py: .../src/py/app
    # Index of "src" is found, so it should map to "py.app"
    assert "py.app" in imports_graph
    assert imports_graph["py.app"] == ["json"]

    # Go module name should map to the relative path/file path without extension
    go_key = str((go_dir / "main").relative_to(tmp_path.parent))
    # Or check if there's any key ending in "/go/main" or "go/main"
    matched_key = next((k for k in imports_graph if k.endswith("go/main")), None)
    assert matched_key is not None
    assert imports_graph[matched_key] == ["strings"]
