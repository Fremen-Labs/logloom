from pathlib import Path
from typing import List
from .model import LogLoomGraph, GraphNode
from .hasher import generate_node_id
from ..scanner.python_scanner import PythonScanner
from ..scanner.regex_fallback import regex_fallback_scan

class GraphBuilder:
    def build(self, source_paths: List[Path], project_name: str = "logloom-project") -> LogLoomGraph:
        scanner = PythonScanner()
        all_sites = []
        
        for path in source_paths:
            if path.is_file():
                sites = scanner.scan_file(path)
                sites.extend(regex_fallback_scan(path))
                all_sites.extend(sites)
            elif path.is_dir():
                for py_file in path.rglob("*.py"):
                    sites = scanner.scan_file(py_file)
                    sites.extend(regex_fallback_scan(py_file))
                    all_sites.extend(sites)

        nodes = {}
        for site in all_sites:
            node_id = generate_node_id(site)
            nodes[node_id] = GraphNode(
                node_id=node_id,
                file=site.file_path,
                module=site.module_path,
                function=site.function_name,
                level=site.log_level,
                message_template=site.message_template,
                line=site.line,
                semantic_tags=[],
            )

        return LogLoomGraph(
            schema_version="1",
            project=project_name,
            built_at="2026-05-12T22:00:00Z",  # TODO: use real timestamp
            nodes=nodes,
        )