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
    mapping_path = out_path.with_name(out_path.stem + "-mapping.json")
    console.print(f"✅ Exported {line_count} docs → {out_path}")
    console.print(f"   [dim]Mapping: {mapping_path}[/dim]")
    console.print()
    console.print("   [dim]# Step 1: Create index with mapping[/dim]")
    console.print(f"   [dim]curl -s -XPUT 'http://localhost:9200/{index_name}' -H 'Content-Type: application/json' -d @{mapping_path}[/dim]")
    console.print("   [dim]# Step 2: Bulk import[/dim]")
    console.print(f"   [dim]curl -s -XPOST 'http://localhost:9200/_bulk' -H 'Content-Type: application/x-ndjson' --data-binary @{out_path}[/dim]")


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


@es.command()
@click.option("--policy-name", default="logloom-enrich", help="Enrich policy name.")
@click.option("--pipeline-name", default="logloom-pipeline", help="Ingest pipeline name.")
@click.option("--source-index", default="logloom-enrichment", help="Enrichment source index.")
@click.option("--output", default=None, help="Write to file instead of stdout.")
def pipeline(policy_name: str, pipeline_name: str, source_index: str, output: str):
    """Generate Elasticsearch enrich policy and ingest pipeline.

    Produces the JSON bodies for:
      1. PUT _enrich/policy/<name>       — the enrich policy
      2. PUT _ingest/pipeline/<name>     — the ingest pipeline

    Together these enable automatic code-context enrichment: any log
    document arriving with a logloom.node_id field gets the full
    semantic context (module, function, tags, call-graph) joined
    from the enrichment index at ingest time.
    """
    import json
    from ..elasticsearch.mapping import generate_enrich_policy, generate_enrich_pipeline

    policy = generate_enrich_policy(policy_name=policy_name, source_index=source_index)
    pipe = generate_enrich_pipeline(pipeline_name=pipeline_name, policy_name=policy_name)

    result = {
        "enrich_policy": {
            "api": f"PUT _enrich/policy/{policy_name}",
            "body": policy,
        },
        "ingest_pipeline": {
            "api": f"PUT _ingest/pipeline/{pipeline_name}",
            "body": pipe,
        },
        "usage": {
            "step_1": f"PUT _enrich/policy/{policy_name}  (create policy)",
            "step_2": f"POST _enrich/policy/{policy_name}/_execute  (build enrich index)",
            "step_3": f"PUT _ingest/pipeline/{pipeline_name}  (create pipeline)",
            "step_4": f"PUT /my-logs/_settings  {{ \"index.default_pipeline\": \"{pipeline_name}\" }}",
        },
    }

    formatted = json.dumps(result, indent=2)

    if output:
        Path(output).write_text(formatted, encoding="utf-8")
        console.print(f"✅ Pipeline config written to {output}")
    else:
        console.print(formatted)

    console.print()
    console.print("[bold]Deployment steps:[/bold]")
    console.print(f"  1. [cyan]PUT _enrich/policy/{policy_name}[/cyan]")
    console.print(f"  2. [cyan]POST _enrich/policy/{policy_name}/_execute[/cyan]")
    console.print(f"  3. [cyan]PUT _ingest/pipeline/{pipeline_name}[/cyan]")
    console.print(f"  4. Assign pipeline to your log index")

