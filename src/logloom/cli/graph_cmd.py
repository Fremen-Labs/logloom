"""Issue #17 — logloom graph stats / show CLI commands."""

import click
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.tree import Tree
from rich.panel import Panel
from collections import Counter

from ..graph.store import load_graph

console = Console()


@click.group()
def graph():
    """Inspect and explore the LogLoom knowledge graph."""
    pass


@graph.command()
@click.option("--graph-path", default="logloom-graph.json", help="Path to graph JSON.")
def stats(graph_path: str):
    """Show high-level statistics about the knowledge graph."""
    g = load_graph(Path(graph_path))
    if not g:
        console.print("[red]❌ Could not load graph.[/red]")
        return

    nodes = list(g.nodes.values())

    # ── Aggregate stats ───────────────────────────────────────────────────
    modules = set(n.module for n in nodes)
    functions = set(n.function for n in nodes)
    files = set(n.file for n in nodes)
    all_tags = []
    for n in nodes:
        all_tags.extend(n.semantic_tags)
    tag_counts = Counter(all_tags)
    level_counts = Counter(n.level for n in nodes)

    total_call_parents = sum(len(n.call_parents) for n in nodes)
    total_call_children = sum(len(n.call_children) for n in nodes)
    total_edges = (total_call_parents + total_call_children) // 2  # each edge counted twice

    # ── Display ───────────────────────────────────────────────────────────
    console.print(Panel.fit(
        f"[bold blue]{g.project}[/bold blue]  •  schema v{g.schema_version}",
        subtitle=f"Built {g.built_at[:19]}",
    ))

    table = Table(title="Graph Overview", show_header=False, border_style="dim")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Log sites", str(len(nodes)))
    table.add_row("Files", str(len(files)))
    table.add_row("Modules", str(len(modules)))
    table.add_row("Functions", str(len(functions)))
    table.add_row("Call-graph edges", str(total_edges))
    if g.commit_sha:
        table.add_row("Commit", g.commit_sha[:12])
    if g.branch:
        table.add_row("Branch", g.branch)
    if g.redacted_patterns:
        table.add_row("Redacted patterns", ", ".join(g.redacted_patterns))
    console.print(table)

    if g.coverage:
        cov_table = Table(title="Log Coverage Metrics", show_header=False, border_style="dim")
        cov_table.add_column("Metric", style="bold")
        cov_table.add_column("Value", justify="right")
        cov_table.add_row("Coverage Percentage", f"{g.coverage.coverage_pct}%")
        cov_table.add_row("Instrumented Functions", str(g.coverage.instrumented_functions))
        cov_table.add_row("Total Functions", str(g.coverage.total_functions))
        console.print(cov_table)

        if g.coverage.uninstrumented:
            uninst_table = Table(title="⚠️  Uninstrumented Functions (No Log Sites)", border_style="yellow")
            uninst_table.add_column("Function", style="bold yellow")
            for func in sorted(g.coverage.uninstrumented[:20]):
                uninst_table.add_row(func)

            extra = len(g.coverage.uninstrumented) - 20
            if extra > 0:
                uninst_table.add_row(f"... and {extra} more functions")
            console.print(uninst_table)

    if level_counts:
        level_table = Table(title="Levels", border_style="dim")
        level_table.add_column("Level", style="bold")
        level_table.add_column("Count", justify="right")
        for level, count in level_counts.most_common():
            style = "red" if level in ("error", "critical", "exception") else "yellow" if level == "warning" else ""
            level_table.add_row(f"[{style}]{level}[/{style}]" if style else level, str(count))
        console.print(level_table)

    if tag_counts:
        tag_table = Table(title="Semantic Tags", border_style="dim")
        tag_table.add_column("Tag", style="bold cyan")
        tag_table.add_column("Count", justify="right")
        for tag, count in tag_counts.most_common():
            tag_table.add_row(tag, str(count))
        console.print(tag_table)


@graph.command()
@click.option("--graph-path", default="logloom-graph.json", help="Path to graph JSON.")
@click.option("--format", "fmt", type=click.Choice(["tree", "flat"]), default="tree", help="Output format.")
def show(graph_path: str, fmt: str):
    """Display the knowledge graph as a tree or flat list."""
    g = load_graph(Path(graph_path))
    if not g:
        console.print("[red]❌ Could not load graph.[/red]")
        return

    if fmt == "tree":
        _show_tree(g)
    else:
        _show_flat(g)


@graph.command()
@click.argument("query")
@click.option("--graph-path", default="logloom-graph.json", help="Path to graph JSON.")
def find(query: str, graph_path: str):
    """Search for a node by message template substring."""
    g = load_graph(Path(graph_path))
    if not g:
        console.print("[red]❌ Could not load graph.[/red]")
        return

    matches = [
        n for n in g.nodes.values()
        if query.lower() in n.message_template.lower()
        or query.lower() in n.function.lower()
        or query.lower() in n.module.lower()
    ]

    if not matches:
        console.print(f"[yellow]No nodes matching '{query}'[/yellow]")
        return

    table = Table(title=f"Nodes matching '{query}'", border_style="dim")
    table.add_column("ID", style="bold cyan", no_wrap=True)
    table.add_column("File:Line")
    table.add_column("Function")
    table.add_column("Message")
    table.add_column("Tags", style="dim")

    for n in matches:
        table.add_row(
            n.node_id,
            f"{n.file}:{n.line}",
            n.function,
            n.message_template[:50],
            ", ".join(n.semantic_tags),
        )

    console.print(table)


# ── Internal Helpers ──────────────────────────────────────────────────────────

def _show_tree(g):
    """Render the graph as a rich Tree, grouped by module → function."""
    root = Tree(f"[bold blue]{g.project}[/bold blue] ({len(g.nodes)} nodes)")

    # Group: module → function → nodes
    modules = {}
    for n in g.nodes.values():
        modules.setdefault(n.module, {}).setdefault(n.function, []).append(n)

    for mod_name in sorted(modules):
        mod_branch = root.add(f"[bold]{mod_name}[/bold]")
        for func_name in sorted(modules[mod_name]):
            func_branch = mod_branch.add(f"[cyan]{func_name}()[/cyan]")
            for node in modules[mod_name][func_name]:
                tags = f" [dim][{', '.join(node.semantic_tags)}][/dim]" if node.semantic_tags else ""
                level_color = "red" if node.level in ("error", "critical") else "yellow" if node.level == "warning" else "green"
                func_branch.add(
                    f"[{level_color}]{node.level}[/{level_color}] "
                    f"\"{node.message_template}\" "
                    f"[dim]({node.node_id})[/dim]{tags}"
                )

    console.print(root)


def _show_flat(g):
    """Render the graph as a flat table."""
    table = Table(title=f"{g.project} — {len(g.nodes)} nodes", border_style="dim")
    table.add_column("ID", style="bold cyan", no_wrap=True)
    table.add_column("Level")
    table.add_column("File:Line")
    table.add_column("Function")
    table.add_column("Message")
    table.add_column("Tags", style="dim")

    for n in sorted(g.nodes.values(), key=lambda x: (x.file, x.line)):
        level_color = "red" if n.level in ("error", "critical") else "yellow" if n.level == "warning" else ""
        table.add_row(
            n.node_id,
            f"[{level_color}]{n.level}[/{level_color}]" if level_color else n.level,
            f"{n.file}:{n.line}",
            n.function,
            n.message_template[:60],
            ", ".join(n.semantic_tags),
        )

    console.print(table)
