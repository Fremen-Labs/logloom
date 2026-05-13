from pathlib import Path
from typing import List
from datetime import datetime, timezone
from .model import LogLoomGraph, GraphNode
from .hasher import NodeHasher
from ..scanner.python_scanner import PythonScanner
from ..scanner.regex_fallback import regex_fallback_scan

class GraphBuilder:
    def build(self, source_paths: List[Path], project_name: str = "logloom-project", redact_patterns: List[str] = None) -> LogLoomGraph:
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

        hasher = NodeHasher()
        nodes = {}
        for site in all_sites:
            # Phase 1: lexical parent scope
            parent_scope = site.lexical_context.get("enclosing_function", "") if site.lexical_context else ""
            
            node_id = hasher.generate_node_id(
                module_path=site.module_path,
                class_name=site.class_name,
                function_name=site.function_name,
                message_template=site.message_template,
                file_path=site.file_path,
                parent_scope=parent_scope
            )
            
            # Extract basic tags
            semantic_tags = []
            if "error" in site.log_level.lower() or "critical" in site.log_level.lower():
                semantic_tags.append("error")
                
            # Redaction
            msg_template = site.message_template
            if redact_patterns:
                lower_msg = msg_template.lower()
                for pattern in redact_patterns:
                    if pattern.lower() in lower_msg:
                        msg_template = "[REDACTED]"
                        break

            nodes[node_id] = GraphNode(
                node_id=node_id,
                file=site.file_path,
                module=site.module_path,
                function=site.function_name,
                level=site.log_level,
                message_template=msg_template,
                line=site.line,
                semantic_tags=semantic_tags,
                lexical_parents=[parent_scope] if parent_scope else []
            )

        # Remove duplicate nodes by ID (which could happen if scanner and regex find the exact same thing)
        
        return LogLoomGraph(
            schema_version="1",
            project=project_name,
            built_at=datetime.now(timezone.utc).isoformat(),
            nodes=nodes,
            redacted_patterns=redact_patterns or []
        )