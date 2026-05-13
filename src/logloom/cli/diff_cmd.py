"""Issue #19 — logloom diff CLI command."""

import click
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ..graph.model import LogLoomGraph
from ..intelligence.diff import diff_graphs

console = Console()


@click.command()
@click.argument("old_graph", type=click.Path(exists=True))
@click.argument("new_graph", type=click.Path(exists=True))
@click.option("--strict", is_flag=True, help="Exit with code 1 if removals are detected.")
def diff(old_graph: str, new_graph: str, strict: bool):
    """Compare two graph versions and show changes."""
    old = LogLoomGraph.load(old_graph)
    new = LogLoomGraph.load(new_graph)

    result = diff_graphs(old, new)

    if not result.has_changes:
        console.print(Panel.fit("[bold green]✅ No changes detected.[/bold green]"))
        return

    console.print(Panel.fit(
        f"[bold]{result.summary()}[/bold]",
        title="Graph Diff",
        subtitle=f"{result.old_version[:19]} → {result.new_version[:19]}",
    ))

    if result.added:
        table = Table(title=f"➕ Added ({len(result.added)})", border_style="green")
        table.add_column("Node ID", style="cyan")
        table.add_column("Details")
        for change in result.added:
            table.add_row(change.node_id, change.details)
        console.print(table)

    if result.removed:
        table = Table(title=f"➖ Removed ({len(result.removed)})", border_style="red")
        table.add_column("Node ID", style="cyan")
        table.add_column("Details")
        for change in result.removed:
            table.add_row(change.node_id, change.details)
        console.print(table)

    if result.moved:
        table = Table(title=f"↔️  Moved ({len(result.moved)})", border_style="yellow")
        table.add_column("Node ID", style="cyan")
        table.add_column("Details")
        for change in result.moved:
            table.add_row(change.node_id, change.details)
        console.print(table)

    if result.modified:
        table = Table(title=f"Δ Modified ({len(result.modified)})", border_style="blue")
        table.add_column("Node ID", style="cyan")
        table.add_column("Details")
        for change in result.modified:
            table.add_row(change.node_id, change.details)
        console.print(table)

    if strict and result.removed:
        raise SystemExit(1)
