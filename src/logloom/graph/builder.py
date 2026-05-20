import re
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timezone
from .model import LogLoomGraph, GraphNode, FunctionSignature, Parameter
from .hasher import NodeHasher
from ..scanner.python_scanner import PythonScanner
from ..scanner.regex_fallback import regex_fallback_scan


def _detect_project_name(source_paths: List[Path]) -> str:
    """Auto-detect project name from pyproject.toml, setup.cfg, or directory name.

    Walks up from the first source path looking for project metadata files.
    Falls back to the source directory name.
    """
    start = source_paths[0].resolve() if source_paths else Path.cwd()
    search_dir = start if start.is_dir() else start.parent

    # Walk up looking for pyproject.toml or setup.cfg
    current = search_dir
    for _ in range(10):
        # Try pyproject.toml
        pyproject = current / "pyproject.toml"
        if pyproject.exists():
            try:
                text = pyproject.read_text(encoding="utf-8")
                # Parse [project] name = "..."
                match = re.search(r'^name\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
                if match:
                    return match.group(1)
            except Exception:
                pass

        # Try setup.cfg
        setup_cfg = current / "setup.cfg"
        if setup_cfg.exists():
            try:
                text = setup_cfg.read_text(encoding="utf-8")
                match = re.search(r'^name\s*=\s*(.+)$', text, re.MULTILINE)
                if match:
                    return match.group(1).strip()
            except Exception:
                pass

        parent = current.parent
        if parent == current:
            break
        current = parent

    # Fallback: use the source directory name
    return search_dir.name or "logloom-project"

# File extensions that each scanner handles
_PYTHON_EXTS = {".py"}
_GO_EXTS = {".go"}
_TS_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


class GraphBuilder:
    def build(
        self,
        source_paths: List[Path],
        project_name: Optional[str] = None,
        redact_patterns: Optional[List[str]] = None,
        enable_tags: bool = True,
        enable_call_graph: bool = True,
        enable_git: bool = True,
        enable_coverage: bool = True,
        enable_models: bool = True,
        enable_imports: bool = True,
        languages: Optional[List[str]] = None,
        include_external_imports: bool = False,
    ) -> LogLoomGraph:
        """Build the LogLoom knowledge graph from source files.

        Args:
            source_paths: Files or directories to scan.
            project_name: Project name for the graph metadata.
            redact_patterns: Sensitive terms to scrub from message templates.
            enable_tags: Run the semantic tag inference pass (Issue #14).
            enable_call_graph: Run the call-graph edge resolver (Issue #15).
            enable_git: Embed git metadata (Issue #16).
            languages: List of language codes to scan. Default: ["python"].
                       Options: "python", "go", "typescript".
        """
        if project_name is None:
            project_name = _detect_project_name(source_paths)

        if languages is None:
            languages = ["python"]

        all_sites = []

        # ── Collect files ─────────────────────────────────────────────────
        all_files = []
        for path in source_paths:
            if path.is_file():
                all_files.append(path)
            elif path.is_dir():
                all_files.extend(path.rglob("*"))

        # ── Python scanning ───────────────────────────────────────────────
        if "python" in languages:
            scanner = PythonScanner()
            for f in all_files:
                if f.suffix in _PYTHON_EXTS:
                    all_sites.extend(scanner.scan_file(f))
                    all_sites.extend(regex_fallback_scan(f))

        # ── Go scanning (Issue #23) ───────────────────────────────────────
        if "go" in languages:
            try:
                from ..scanner.go_scanner import GoScanner
                go_scanner = GoScanner(exclude_tests=True)
                if go_scanner.available:
                    for f in all_files:
                        if f.suffix in _GO_EXTS:
                            all_sites.extend(go_scanner.scan_file(f))
            except ImportError:
                pass  # tree-sitter-go not installed

        # ── TypeScript/JavaScript scanning (Issue #24) ────────────────────
        if "typescript" in languages:
            try:
                from ..scanner.ts_scanner import TypeScriptScanner
                ts_scanner = TypeScriptScanner()
                if ts_scanner.available:
                    for f in all_files:
                        if f.suffix in _TS_EXTS:
                            all_sites.extend(ts_scanner.scan_file(f))
            except ImportError:
                pass  # tree-sitter-typescript not installed

        # Deduplicate sites by (file_path, line) giving priority to AST scanner
        unique_sites = {}
        for site in all_sites:
            key = (site.file_path, site.line)
            if key not in unique_sites:
                unique_sites[key] = site

        hasher = NodeHasher()
        nodes = {}
        for site in unique_sites.values():
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

            # Basic semantic tags from level (the tagger will enrich further)
            semantic_tags = []
            if site.log_level.lower() in ("error", "critical", "exception"):
                semantic_tags.append("error")

            # Redaction
            msg_template = site.message_template
            if redact_patterns:
                lower_msg = msg_template.lower()
                for pattern in redact_patterns:
                    if pattern.lower() in lower_msg:
                        msg_template = "[REDACTED]"
                        break

            # Phase B: Build FunctionSignature from scanner data
            sig = None
            if site.signature:
                sig = FunctionSignature(
                    parameters=[
                        Parameter(**p) for p in site.signature.get("parameters", [])
                    ],
                    return_type=site.signature.get("return_type"),
                    is_async=site.signature.get("is_async", False),
                    decorators=site.signature.get("decorators", []),
                )

            nodes[node_id] = GraphNode(
                node_id=node_id,
                file=site.file_path,
                module=site.module_path,
                function=site.function_name,
                level=site.log_level,
                message_template=msg_template,
                line=site.line,
                semantic_tags=semantic_tags,
                lexical_parents=[parent_scope] if parent_scope else [],
                signature=sig,
            )

        graph = LogLoomGraph(
            schema_version="1.2",
            project=project_name,
            built_at=datetime.now(timezone.utc).isoformat(),
            nodes=nodes,
            redacted_patterns=redact_patterns or []
        )

        # ── Milestone 2 Intelligence Passes ───────────────────────────────
        if enable_tags:
            try:
                from ..intelligence.tagger import infer_tags
                graph = infer_tags(graph)
            except ImportError:
                pass  # Build-time deps not installed

        if enable_call_graph:
            try:
                from ..intelligence.call_graph import CallGraphResolver
                resolver = CallGraphResolver()
                graph = resolver.resolve(graph, source_paths)
            except ImportError:
                pass  # Build-time deps not installed

        if enable_git:
            try:
                from ..intelligence.git_meta import enrich_graph_with_git
                graph = enrich_graph_with_git(graph)
            except ImportError:
                pass

        if enable_coverage:
            try:
                from ..intelligence.coverage import compute_coverage
                graph.coverage = compute_coverage(graph, source_paths, languages)
            except Exception:
                pass

        if enable_models:
            try:
                from ..scanner.model_scanner import scan_models
                graph.models = scan_models(source_paths, languages)
            except Exception:
                pass

        if enable_imports:
            try:
                from ..intelligence.import_graph import compute_imports
                graph.imports = compute_imports(source_paths, languages, include_external=include_external_imports)
            except Exception:
                pass

        return graph