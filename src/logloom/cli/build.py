import click
from pathlib import Path
from ..graph.builder import GraphBuilder
from ..graph.store import save_graph

@click.command()
@click.option("--source", default=".", help="Source directory or file")
@click.option("--output", default="logloom-graph.json")
@click.option("--verbose", is_flag=True)
@click.option("--redact-patterns", default="", help="Comma-separated list of sensitive terms to redact from message templates")
def build(source: str, output: str, verbose: bool, redact_patterns: str):
    """Build the LogLoom knowledge graph."""
    source_path = Path(source)
    if not source_path.exists():
        click.echo(f"❌ Source path {source} does not exist")
        return 1

    builder = GraphBuilder()
    patterns = [p.strip() for p in redact_patterns.split(",")] if redact_patterns else []
    graph = builder.build([source_path], redact_patterns=patterns)

    save_graph(graph, Path(output))
    click.echo(f"✅ Built graph with {len(graph.nodes)} nodes → {output}")