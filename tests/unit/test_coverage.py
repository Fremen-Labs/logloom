"""Tests for Phase C: Coverage Metrics."""

import pytest
from pathlib import Path
from logloom.graph.model import LogLoomGraph, GraphNode
from logloom.intelligence.coverage import (
    compute_coverage,
    _extract_python_functions,
    _extract_go_functions,
    _extract_ts_functions,
)


def test_extract_python_functions(tmp_path):
    py_code = """
def normal_func():
    pass

class MyClass:
    def method_one(self):
        pass
        
    def method_two(self):
        pass
"""
    f = tmp_path / "test_module.py"
    f.write_text(py_code, encoding="utf-8")
    funcs = _extract_python_functions(f)
    assert any(func.endswith(":normal_func") for func in funcs)
    assert any(func.endswith(":method_one") for func in funcs)
    assert any(func.endswith(":method_two") for func in funcs)
    assert len(funcs) == 3


def test_extract_go_functions(tmp_path):
    go_code = """
package main

func normalGoFunc() {}

type MyStruct struct{}

func (m *MyStruct) MyMethod() {}
"""
    f = tmp_path / "main.go"
    f.write_text(go_code, encoding="utf-8")
    funcs = _extract_go_functions(f)
    assert any(func.endswith(":normalGoFunc") for func in funcs)
    assert any(func.endswith(":MyStruct.MyMethod") for func in funcs)
    assert len(funcs) == 2


def test_extract_ts_functions(tmp_path):
    ts_code = """
function normalTSFunc() {}

class MyClass {
    methodOne() {}
}

const arrowFunc = () => {}
"""
    f = tmp_path / "main.ts"
    f.write_text(ts_code, encoding="utf-8")
    funcs = _extract_ts_functions(f)
    assert any(func.endswith(":normalTSFunc") for func in funcs)
    assert any(func.endswith(":MyClass.methodOne") for func in funcs)
    assert any(func.endswith(":arrowFunc") for func in funcs)
    assert len(funcs) == 3


def test_compute_coverage(tmp_path):
    src_dir = tmp_path / "src" / "myproj"
    src_dir.mkdir(parents=True)

    py_code = """
def instrumented_func():
    pass

def uninstrumented_func():
    pass
"""
    f = src_dir / "app.py"
    f.write_text(py_code, encoding="utf-8")

    nodes = {
        "node1": GraphNode(
            node_id="node1",
            file=str(f),
            module="myproj.app",
            function="instrumented_func",
            level="info",
            message_template="hello",
            line=5,
        )
    }
    graph = LogLoomGraph(project="test", built_at="2026", nodes=nodes)

    metrics = compute_coverage(graph, [src_dir], ["python"])

    assert metrics.total_functions == 2
    assert metrics.instrumented_functions == 1
    assert metrics.coverage_pct == 50.0
    assert metrics.uninstrumented == ["myproj.app:uninstrumented_func"]
