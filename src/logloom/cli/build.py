import click
from pathlib import Path
from ..graph.builder import GraphBuilder
from ..graph.store import save_graph

@click.command()
@click.option("--source", default=".", help="Source directory or file to scan.")
@click.option("--output", default="logloom-graph.json", help="Output graph path.")
@click.option("--verbose", is_flag=True, help="Show discovered log sites.")
@click.option("--redact-patterns", default="", help="Comma-separated sensitive terms to redact from templates.")
@click.option("--git/--no-git", default=True, help="Embed git metadata (commit SHA, branch).")
@click.option("--tags/--no-tags", default=True, help="Run semantic tag auto-inference.")
@click.option("--call-graph/--no-call-graph", default=True, help="Resolve inter-function call-graph edges.")
@click.option("--coverage/--no-coverage", default=True, help="Compute scan completeness and log coverage metrics.")
@click.option("--models/--no-models", default=True, help="Extract data model definitions (dataclasses, structs, interfaces).")
@click.option("--imports/--no-imports", default=True, help="Extract module-level import relationships.")
@click.option("--incremental/--no-incremental", default=True, help="Reuse scanned files when unchanged.")
@click.option("--languages", default="python", help="Comma-separated languages: python,go,typescript.")
@click.option("--name", "project_name", default=None, help="Project name (auto-detected from pyproject.toml or directory).")
@click.option("--external-imports", is_flag=True, help="Include external/third-party modules in the import graph.")
@click.option("--min-coverage", type=float, default=None, help="Fail the build if log coverage percentage is below this threshold.")
def build(source: str, output: str, verbose: bool, redact_patterns: str, git: bool, tags: bool, call_graph: bool, coverage: bool, models: bool, imports: bool, incremental: bool, languages: str, project_name: str, external_imports: bool, min_coverage: float):
    """Build the LogLoom knowledge graph from source code."""
    source_path = Path(source)
    if not source_path.exists():
        click.echo(f"❌ Source path {source} does not exist")
        return 1

    builder = GraphBuilder()
    patterns = [p.strip() for p in redact_patterns.split(",")] if redact_patterns else []
    lang_list = [l.strip() for l in languages.split(",") if l.strip()]

    graph = builder.build(
        [source_path],
        project_name=project_name,
        redact_patterns=patterns,
        enable_tags=tags,
        enable_call_graph=call_graph,
        enable_git=git,
        enable_coverage=coverage,
        enable_models=models,
        enable_imports=imports,
        languages=lang_list,
        include_external_imports=external_imports,
        enable_incremental=incremental,
    )

    if verbose:
        for node in graph.nodes.values():
            tags_str = f" [{', '.join(node.semantic_tags)}]" if node.semantic_tags else ""
            click.echo(f"  📍 {node.file}:{node.line} {node.function}() → \"{node.message_template}\"{tags_str}")

    save_graph(graph, Path(output))

    # Summary line
    tag_count = sum(len(n.semantic_tags) for n in graph.nodes.values())
    edge_count = sum(len(n.call_parents) + len(n.call_children) for n in graph.nodes.values())
    parts = [f"{len(graph.nodes)} nodes"]
    if tag_count:
        parts.append(f"{tag_count} tags")
    if edge_count:
        parts.append(f"{edge_count} edges")
    if len(graph.models) > 0:
        parts.append(f"{len(graph.models)} models")
    if len(graph.imports) > 0:
        parts.append(f"{len(graph.imports)} modules")
    if graph.coverage:
        parts.append(f"{graph.coverage.coverage_pct}% coverage ({graph.coverage.instrumented_functions}/{graph.coverage.total_functions} functions)")
    if graph.commit_sha:
        parts.append(f"commit {graph.commit_sha[:8]}")

    click.echo(f"✅ Built graph: {', '.join(parts)} → {output}")

    if min_coverage is not None and graph.coverage:
        if graph.coverage.coverage_pct < min_coverage:
            click.echo(f"❌ Build failed: coverage {graph.coverage.coverage_pct}% is below required minimum threshold {min_coverage}%", err=True)
            raise SystemExit(1)