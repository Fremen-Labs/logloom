import click
from pathlib import Path
from ..graph.builder import GraphBuilder
from ..graph.store import save_graph

@click.command()
@click.option("--source", default=".", help="Source directory or file")
@click.option("--output", default="logloom-graph.json")
@click.option("--verbose", is_flag=True)
def build(source: str, output: str, verbose: bool):
    """Build the LogLoom knowledge graph."""
    source_path = Path(source)
    if not source_path.exists():
        click.echo(f"❌ Source path {source} does not exist")
        return 1

    builder = GraphBuilder()
    graph = builder.build([source_path])

    save_graph(graph, Path(output))
    click.echo(f"✅ Built graph with {len(graph.nodes)} nodes → {output}")