"""Issue #18 — logloom lint — detect untracked log sites.

Scans source files for log calls and compares against an existing graph
to find sites that are not yet tracked, or sites in the graph that no
longer exist in code.
"""

import click
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ..graph.store import load_graph
from ..scanner.python_scanner import PythonScanner
from ..scanner.regex_fallback import regex_fallback_scan

console = Console()


@click.command()
@click.option("--source", default=".", help="Source directory to scan.")
@click.option("--graph-path", default="logloom-graph.json", help="Path to existing graph.")
@click.option("--strict", is_flag=True, help="Exit with code 1 if untracked sites are found.")
def lint(source: str, graph_path: str, strict: bool):
    """Detect log sites not captured by the knowledge graph."""
    source_path = Path(source)
    if not source_path.exists():
        console.print(f"[red]❌ Source path {source} does not exist[/red]")
        raise SystemExit(1)

    g = load_graph(Path(graph_path))
    if not g:
        console.print(f"[red]❌ Could not load graph from {graph_path}[/red]")
        console.print("Run [bold cyan]logloom build --source {source}[/bold cyan] first.")
        raise SystemExit(1)

    # ── Scan source for current log sites ─────────────────────────────────
    scanner = PythonScanner()
    discovered = {}  # (file, line) → LogCallSite

    files = [source_path] if source_path.is_file() else list(source_path.rglob("*.py"))
    for py_file in files:
        for site in scanner.scan_file(py_file):
            discovered[(site.file_path, site.line)] = site
        for site in regex_fallback_scan(py_file):
            key = (site.file_path, site.line)
            if key not in discovered:
                discovered[key] = site

    # ── Build lookup sets ─────────────────────────────────────────────────
    graph_locations = set()
    for node in g.nodes.values():
        graph_locations.add((node.file, node.line))

    discovered_locations = set(discovered.keys())

    untracked = discovered_locations - graph_locations
    stale = graph_locations - discovered_locations

    # ── Report ────────────────────────────────────────────────────────────
    if not untracked and not stale:
        console.print(Panel.fit(
            f"[bold green]✅ All {len(discovered)} log sites are tracked.[/bold green]",
            subtitle="Graph is in sync",
        ))
        return

    if untracked:
        table = Table(title=f"⚠️  {len(untracked)} Untracked Log Sites", border_style="yellow")
        table.add_column("File", style="bold")
        table.add_column("Line", justify="right")
        table.add_column("Function")
        table.add_column("Level")
        table.add_column("Message")

        for file_path, line in sorted(untracked):
            site = discovered.get((file_path, line))
            if site:
                table.add_row(
                    str(site.file_path),
                    str(site.line),
                    site.function_name,
                    site.log_level,
                    site.message_template[:60],
                )

        console.print(table)

    if stale:
        table = Table(title=f"🗑️  {len(stale)} Stale Graph Entries", border_style="red")
        table.add_column("File", style="bold")
        table.add_column("Line", justify="right")
        table.add_column("Node ID", style="cyan")

        for file_path, line in sorted(stale):
            # Find the node
            for node in g.nodes.values():
                if node.file == file_path and node.line == line:
                    table.add_row(str(file_path), str(line), node.node_id)
                    break

        console.print(table)

    console.print(
        f"\n[bold]Summary:[/bold] {len(untracked)} untracked, {len(stale)} stale. "
        f"Run [bold cyan]logloom build --source {source}[/bold cyan] to regenerate."
    )

    if strict and untracked:
        raise SystemExit(1)
