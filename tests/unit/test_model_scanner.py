"""Tests for Phase D: Data Model Extraction."""

import pytest
from pathlib import Path
from logloom.scanner.model_scanner import (
    scan_models,
    _extract_python_models,
    _extract_go_models,
    _extract_ts_models,
)


def test_extract_python_models(tmp_path):
    py_code = """
from pydantic import BaseModel
from typing import TypedDict
from dataclasses import dataclass

@dataclass
class User:
    id: int
    name: str = "Anonymous"

class Task(BaseModel):
    title: str
    done: bool = False

class Config(TypedDict):
    port: int
    host: str
"""
    f = tmp_path / "models.py"
    f.write_text(py_code, encoding="utf-8")

    models = _extract_python_models(f)
    assert len(models) == 3

    user = next(m for m in models if m.name == "User")
    assert user.file == str(f)
    assert "dataclass" in user.file or len(user.fields) == 2
    assert any(f.name == "id" and f.type_hint == "int" for f in user.fields)
    assert any(f.name == "name" and f.type_hint == "str" and f.default == '"Anonymous"' for f in user.fields)

    task = next(m for m in models if m.name == "Task")
    assert "BaseModel" in task.base_classes
    assert any(f.name == "title" and f.type_hint == "str" for f in task.fields)
    assert any(f.name == "done" and f.type_hint == "bool" and f.default == "False" for f in task.fields)

    config = next(m for m in models if m.name == "Config")
    assert "TypedDict" in config.base_classes
    assert any(f.name == "port" and f.type_hint == "int" for f in config.fields)


def test_extract_go_models(tmp_path):
    go_code = """
package main

type Task struct {
	ID    string `json:"id"`
	Title string `json:"title"`
	Done  bool   `json:"done"`
}

type MyInt int
"""
    f = tmp_path / "main.go"
    f.write_text(go_code, encoding="utf-8")

    models = _extract_go_models(f)
    assert len(models) == 1
    task = models[0]
    assert task.name == "Task"
    assert len(task.fields) == 3
    assert any(f.name == "ID" and f.type_hint == "string" and f.default == 'json:"id"' for f in task.fields)
    assert any(f.name == "Title" and f.type_hint == "string" and f.default == 'json:"title"' for f in task.fields)
    assert any(f.name == "Done" and f.type_hint == "bool" and f.default == 'json:"done"' for f in task.fields)


def test_extract_ts_models(tmp_path):
    ts_code = """
interface Task extends BaseTask {
    id: string;
    title: string;
    done?: boolean;
}

type Config = {
    port: number;
    host: string;
};
"""
    f = tmp_path / "main.ts"
    f.write_text(ts_code, encoding="utf-8")

    models = _extract_ts_models(f)
    assert len(models) == 2

    task = next(m for m in models if m.name == "Task")
    assert "BaseTask" in task.base_classes
    assert any(f.name == "id" and f.type_hint == "string" for f in task.fields)
    assert any(f.name == "done" and f.type_hint == "boolean (optional)" for f in task.fields)

    config = next(m for m in models if m.name == "Config")
    assert any(f.name == "port" and f.type_hint == "number" for f in config.fields)


def test_scan_models_e2e(tmp_path):
    py_dir = tmp_path / "py"
    py_dir.mkdir()
    py_code = """
class Task:
    id: int
    title: str
"""
    (py_dir / "app.py").write_text(py_code, encoding="utf-8")

    go_dir = tmp_path / "go"
    go_dir.mkdir()
    go_code = """
package main
type User struct { Name string }
"""
    (go_dir / "main.go").write_text(go_code, encoding="utf-8")

    models = scan_models([tmp_path], ["python", "go"])
    assert "Task" in models
    assert "User" in models
    assert len(models["Task"].fields) == 2
    assert len(models["User"].fields) == 1
