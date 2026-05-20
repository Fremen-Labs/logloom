import re
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timezone
from .model import LogLoomGraph, GraphNode, FunctionSignature, Parameter, ModelDefinition
from .hasher import NodeHasher
from ..scanner.python_scanner import PythonScanner
from ..scanner.regex_fallback import regex_fallback_scan
from .cache import BuildCache, calculate_file_hash
from ..scanner.base import LogCallSite

try:
    from ..scanner.model_scanner import (
        _extract_python_models,
        _extract_go_models,
        _extract_ts_models,
    )
except ImportError:
    _extract_python_models = None
    _extract_go_models = None
    _extract_ts_models = None

try:
    from ..intelligence.import_graph import (
        _extract_python_imports,
        _extract_go_imports,
        _extract_ts_imports,
    )
except ImportError:
    _extract_python_imports = None
    _extract_go_imports = None
    _extract_ts_imports = None

try:
    from ..intelligence.coverage import (
        _extract_python_functions,
        _extract_go_functions,
        _extract_ts_functions,
    )
except ImportError:
    _extract_python_functions = None
    _extract_go_functions = None
    _extract_ts_functions = None


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


def deserialize_site(d: dict) -> LogCallSite:
    return LogCallSite(
        file_path=d["file_path"],
        module_path=d["module_path"],
        class_name=d["class_name"],
        function_name=d["function_name"],
        log_level=d["log_level"],
        message_template=d["message_template"],
        line=d["line"],
        column=d["column"],
        lexical_context=d["lexical_context"],
        signature=d["signature"],
    )


class GraphBuilder:
    def _extract_file_data(self, f: Path, languages: List[str]):
        suffix = f.suffix
        sites = []
        models = []
        imports = []
        defined_functions = []

        # ── Sites ──
        if suffix in _PYTHON_EXTS and "python" in languages:
            sites.extend(PythonScanner().scan_file(f))
            sites.extend(regex_fallback_scan(f))
        elif suffix in _GO_EXTS and "go" in languages:
            if not f.name.endswith("_test.go"):
                try:
                    from ..scanner.go_scanner import GoScanner
                    go_scanner = GoScanner(exclude_tests=True)
                    if go_scanner.available:
                        sites.extend(go_scanner.scan_file(f))
                except ImportError:
                    pass
        elif suffix in _TS_EXTS and "typescript" in languages:
            try:
                from ..scanner.ts_scanner import TypeScriptScanner
                ts_scanner = TypeScriptScanner()
                if ts_scanner.available:
                    sites.extend(ts_scanner.scan_file(f))
            except ImportError:
                pass

        # ── Models ──
        if suffix in _PYTHON_EXTS and "python" in languages:
            try:
                if _extract_python_models:
                    models.extend(_extract_python_models(f))
            except Exception:
                pass
        elif suffix in _GO_EXTS and "go" in languages:
            if not f.name.endswith("_test.go"):
                try:
                    if _extract_go_models:
                        models.extend(_extract_go_models(f))
                except Exception:
                    pass
        elif suffix in _TS_EXTS and "typescript" in languages:
            try:
                if _extract_ts_models:
                    models.extend(_extract_ts_models(f))
            except Exception:
                pass

        # ── Imports ──
        if suffix in _PYTHON_EXTS and "python" in languages:
            try:
                if _extract_python_imports:
                    imports.extend(_extract_python_imports(f))
            except Exception:
                pass
        elif suffix in _GO_EXTS and "go" in languages:
            if not f.name.endswith("_test.go"):
                try:
                    if _extract_go_imports:
                        imports.extend(_extract_go_imports(f))
                except Exception:
                    pass
        elif suffix in _TS_EXTS and "typescript" in languages:
            try:
                if _extract_ts_imports:
                    imports.extend(_extract_ts_imports(f))
            except Exception:
                pass

        # ── Defined Functions ──
        if suffix in _PYTHON_EXTS and "python" in languages:
            try:
                if _extract_python_functions:
                    defined_functions.extend(_extract_python_functions(f))
            except Exception:
                pass
        elif suffix in _GO_EXTS and "go" in languages:
            if not f.name.endswith("_test.go"):
                try:
                    if _extract_go_functions:
                        defined_functions.extend(_extract_go_functions(f))
                except Exception:
                    pass
        elif suffix in _TS_EXTS and "typescript" in languages:
            try:
                if _extract_ts_functions:
                    defined_functions.extend(_extract_ts_functions(f))
            except Exception:
                pass

        return sites, models, imports, defined_functions

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
        enable_incremental: bool = True,
        cache_path: Path = Path(".logloom-cache.json"),
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
            enable_incremental: Reuse previous scan results for unmodified files.
            cache_path: Path to the incremental build cache file.
        """
        if project_name is None:
            project_name = _detect_project_name(source_paths)

        if languages is None:
            languages = ["python"]

        all_sites = []
        all_models = {}
        all_imports = {}
        all_defined_functions = set()

        # ── Collect files ─────────────────────────────────────────────────
        all_files = []
        ignored_names = {"node_modules", "venv", "__pycache__"}
        for path in source_paths:
            if path.is_file():
                parts = path.parent.parts
                if not any(part.startswith(".") or part in ignored_names for part in parts):
                    all_files.append(path)
            elif path.is_dir():
                for p in path.rglob("*"):
                    if p.is_file():
                        try:
                            rel = p.relative_to(path)
                            if any(part.startswith(".") or part in ignored_names for part in rel.parts):
                                continue
                        except Exception:
                            pass
                        all_files.append(p)

        # Filter active files based on languages
        active_files = []
        for f in all_files:
            suffix = f.suffix
            if suffix in _PYTHON_EXTS and "python" in languages:
                active_files.append(f)
            elif suffix in _GO_EXTS and "go" in languages:
                active_files.append(f)
            elif suffix in _TS_EXTS and "typescript" in languages:
                active_files.append(f)

        cache = None
        if enable_incremental:
            cache = BuildCache(cache_path)

        for f in active_files:
            file_hash = calculate_file_hash(f)
            cached_entry = cache.get_file_entry(f) if cache else None

            if cached_entry and cached_entry.get("hash") == file_hash:
                # Cache hit!
                for s_dict in cached_entry.get("sites", []):
                    all_sites.append(deserialize_site(s_dict))

                mod_path = ""
                suffix = f.suffix
                if suffix in _PYTHON_EXTS or suffix in _GO_EXTS or suffix in _TS_EXTS:
                    try:
                        from ..scanner.model_scanner import _get_module_path
                        mod_path = _get_module_path(f)
                    except Exception:
                        pass
                for m_dict in cached_entry.get("models", []):
                    m = ModelDefinition(**m_dict)
                    key = f"{mod_path}.{m.name}" if mod_path else m.name
                    all_models[key] = m

                from ..intelligence.import_graph import _get_py_module_path, _get_go_module_path, _get_ts_module_path
                mod_name = ""
                if suffix in _PYTHON_EXTS:
                    mod_name = _get_py_module_path(f)
                elif suffix in _GO_EXTS:
                    mod_name = _get_go_module_path(f)
                elif suffix in _TS_EXTS:
                    mod_name = _get_ts_module_path(f)
                if mod_name:
                    all_imports[mod_name] = cached_entry.get("imports", [])

                for func in cached_entry.get("defined_functions", []):
                    all_defined_functions.add(func)
            else:
                # Cache miss: scan
                sites, models, imports, defined_functions = self._extract_file_data(f, languages)
                all_sites.extend(sites)

                mod_path = ""
                suffix = f.suffix
                if suffix in _PYTHON_EXTS or suffix in _GO_EXTS or suffix in _TS_EXTS:
                    try:
                        from ..scanner.model_scanner import _get_module_path
                        mod_path = _get_module_path(f)
                    except Exception:
                        pass
                for m in models:
                    key = f"{mod_path}.{m.name}" if mod_path else m.name
                    all_models[key] = m

                from ..intelligence.import_graph import _get_py_module_path, _get_go_module_path, _get_ts_module_path
                mod_name = ""
                if suffix in _PYTHON_EXTS:
                    mod_name = _get_py_module_path(f)
                elif suffix in _GO_EXTS:
                    mod_name = _get_go_module_path(f)
                elif suffix in _TS_EXTS:
                    mod_name = _get_ts_module_path(f)
                if mod_name:
                    all_imports[mod_name] = imports

                for func in defined_functions:
                    all_defined_functions.add(func)

                if cache:
                    cache.set_file_entry(f, file_hash, sites, models, imports, defined_functions)

        if cache:
            cache.clean_unused_entries(active_files)
            cache.save()

        # Deduplicate sites by (file_path, line) giving priority to AST scanner
        unique_sites = {}
        for site in all_sites:
            key = (site.file_path, site.line)
            if key not in unique_sites:
                unique_sites[key] = site

        # ── Compute project root for relative path normalization ──────────
        # Use the common parent of all source paths as the project root.
        # This makes the `file` field portable across machines.
        project_root = None
        resolved_source_paths = [p.resolve() for p in source_paths]
        if resolved_source_paths:
            if len(resolved_source_paths) == 1:
                p = resolved_source_paths[0]
                project_root = p if p.is_dir() else p.parent
            else:
                # Find the common ancestor of all source paths
                try:
                    # Python 3.12+ has Path.parents, use os.path.commonpath
                    import os
                    common = Path(os.path.commonpath([str(p) for p in resolved_source_paths]))
                    project_root = common if common.is_dir() else common.parent
                except ValueError:
                    project_root = resolved_source_paths[0] if resolved_source_paths[0].is_dir() else resolved_source_paths[0].parent

        def _relativize(abs_path_str: str) -> str:
            """Convert an absolute path to a project-relative path."""
            if project_root is None:
                return abs_path_str
            try:
                return str(Path(abs_path_str).resolve().relative_to(project_root))
            except (ValueError, TypeError):
                return abs_path_str

        def _relativize_module(module_str: str) -> str:
            """Relativize a module path if it contains absolute path segments."""
            if project_root is None or not module_str:
                return module_str
            # Only relativize if the module starts with a "/" (absolute path)
            # This catches Go scanner output but preserves Python dot-separated modules
            if module_str.startswith("/"):
                try:
                    return str(Path(module_str).resolve().relative_to(project_root))
                except (ValueError, TypeError):
                    return module_str
            return module_str

        hasher = NodeHasher()
        nodes = {}
        for site in unique_sites.values():
            parent_scope = site.lexical_context.get("enclosing_function", "") if site.lexical_context else ""

            node_id = hasher.generate_node_id(
                module_path=site.module_path,
                class_name=site.class_name,
                function_name=site.function_name,
                message_template=site.message_template,
                file_path=site.file_path,
                parent_scope=parent_scope
            )

            semantic_tags = []
            if site.log_level.lower() in ("error", "critical", "exception"):
                semantic_tags.append("error")

            msg_template = site.message_template
            if redact_patterns:
                lower_msg = msg_template.lower()
                for pattern in redact_patterns:
                    if pattern.lower() in lower_msg:
                        msg_template = "[REDACTED]"
                        break

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
                file=_relativize(site.file_path),
                module=_relativize_module(site.module_path),
                function=site.function_name,
                level=site.log_level,
                message_template=msg_template,
                line=site.line,
                semantic_tags=semantic_tags,
                lexical_parents=[parent_scope] if parent_scope else [],
                signature=sig,
            )

        graph = LogLoomGraph(
            schema_version="2.0",
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
                pass

        if enable_call_graph:
            try:
                from ..intelligence.call_graph import CallGraphResolver
                resolver = CallGraphResolver()
                graph = resolver.resolve(graph, source_paths)
            except ImportError:
                pass

        if enable_git:
            try:
                from ..intelligence.git_meta import enrich_graph_with_git
                graph = enrich_graph_with_git(graph)
            except ImportError:
                pass

        if enable_coverage:
            try:
                from ..intelligence.coverage import compute_coverage
                graph.coverage = compute_coverage(graph, source_paths, languages, defined_functions=all_defined_functions)
            except Exception:
                pass

        if enable_models:
            try:
                from ..scanner.model_scanner import scan_models
                graph.models = scan_models(source_paths, languages, pre_extracted_models=all_models)
            except Exception:
                pass

        if enable_imports:
            try:
                from ..intelligence.import_graph import compute_imports
                graph.imports = compute_imports(source_paths, languages, include_external=include_external_imports, pre_extracted_imports=all_imports)
            except Exception:
                pass

        return graph