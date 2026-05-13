"""Milestone 3 CLI — logloom es (Elasticsearch commands)."""

import click
from pathlib import Path
from rich.console import Console

from ..graph.store import load_graph

console = Console()


@click.group()
def es():
    """Elasticsearch integration commands."""
    pass


@es.command()
@click.option("--type", "template_type", type=click.Choice(["component", "index"]), default="index",
              help="Template type: component (composable) or index (standalone).")
@click.option("--name", default="logloom-logs", help="Template name.")
@click.option("--index-patterns", default="logloom-*,logs-logloom-*",
              help="Comma-separated index patterns.")
@click.option("--ilm-policy", default=None, help="ILM policy name to attach.")
@click.option("--output", default=None, help="Write to file instead of stdout.")
def mapping(template_type: str, name: str, index_patterns: str, ilm_policy: str, output: str):
    """Generate ECS-compatible Elasticsearch mapping templates."""
    from ..elasticsearch.mapping import render_mapping_json

    patterns = [p.strip() for p in index_patterns.split(",")]

    if template_type == "component":
        result = render_mapping_json("component", template_name=name)
    else:
        result = render_mapping_json(
            "index",
            template_name=name,
            index_patterns=patterns,
            ilm_policy=ilm_policy,
        )

    if output:
        Path(output).write_text(result, encoding="utf-8")
        console.print(f"✅ Mapping written to {output}")
    else:
        console.print(result)


@es.command()
@click.option("--graph-path", default="logloom-graph.json", help="Path to graph JSON.")
@click.option("--index", "index_name", default="logloom-enrichment", help="Target index name.")
@click.option("--output", default=None, help="Output NDJSON file path.")
def export(graph_path: str, index_name: str, output: str):
    """Export graph as NDJSON for the Elasticsearch _bulk API."""
    g = load_graph(Path(graph_path))
    if not g:
        console.print(f"[red]❌ Could not load graph from {graph_path}[/red]")
        return

    from ..elasticsearch.shipper import export_ndjson

    out_path = Path(output) if output else Path(f"{index_name}.ndjson")
    ndjson = export_ndjson(g, index_name=index_name, output_path=out_path)

    line_count = len(ndjson.strip().split("\n")) // 2
    console.print(f"✅ Exported {line_count} docs → {out_path}")
    console.print(f"   [dim]curl -XPOST 'http://localhost:9200/_bulk' -H 'Content-Type: application/x-ndjson' --data-binary @{out_path}[/dim]")


@es.command()
@click.option("--graph-path", default="logloom-graph.json", help="Path to graph JSON.")
@click.option("--es-url", default="http://localhost:9200", help="Elasticsearch URL.")
@click.option("--index", "index_name", default="logloom-enrichment", help="Target index.")
@click.option("--api-key", default=None, help="Elasticsearch API key.")
@click.option("--username", default=None, help="Basic auth username.")
@click.option("--password", default=None, help="Basic auth password.")
@click.option("--no-verify", is_flag=True, help="Disable TLS certificate verification.")
def ship(graph_path: str, es_url: str, index_name: str, api_key: str,
         username: str, password: str, no_verify: bool):
    """Ship graph enrichment documents directly to Elasticsearch."""
    g = load_graph(Path(graph_path))
    if not g:
        console.print(f"[red]❌ Could not load graph from {graph_path}[/red]")
        return

    from ..elasticsearch.shipper import ship_to_elasticsearch

    try:
        result = ship_to_elasticsearch(
            g,
            es_url=es_url,
            index_name=index_name,
            api_key=api_key,
            username=username,
            password=password,
            verify_certs=not no_verify,
        )
        console.print(
            f"✅ Shipped {result['success_count']}/{result['total_docs']} docs → "
            f"{es_url}/{index_name}"
        )
        if result['error_count']:
            console.print(f"[red]⚠️  {result['error_count']} errors[/red]")
            for err in result['errors'][:5]:
                console.print(f"   [dim]{err}[/dim]")
    except ImportError as e:
        console.print(f"[red]{e}[/red]")
