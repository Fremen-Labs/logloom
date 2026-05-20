"""logloom report — Codebase Logging Health Assessment.

Generates a comprehensive, human-readable report of logging instrumentation
quality from a LogLoom graph. No Elasticsearch or live logs required.

This is a static analysis tool that answers:
  - Is my error handling visible?
  - Are security-sensitive paths instrumented?
  - Where are my observability dead zones?
  - Is my log-level distribution balanced?

Can be used as a CI/CD quality gate via --min-score.
"""

import click
import math
from pathlib import Path
from collections import Counter
from typing import Dict, List, Optional, Tuple

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich import box

from ..graph.store import load_graph
from ..graph.model import LogLoomGraph

console = Console()


# ── Health scoring weights ────────────────────────────────────────────────────

# Each dimension contributes to the overall score (0-100).
# Weights sum to 1.0.
_WEIGHTS = {
    "level_balance": 0.20,     # Penalize all-info or all-error distributions
    "error_visibility": 0.20,  # Are error paths instrumented?
    "edge_connectivity": 0.20, # Are nodes connected via call-graph edges?
    "function_naming": 0.15,   # % of nodes with real function names (not <module>)
    "signature_coverage": 0.10, # % of nodes with function signatures
    "tag_diversity": 0.15,     # Are semantic tags distributed across domains?
}


def _compute_health(graph: LogLoomGraph) -> dict:
    """Compute all health metrics from the graph."""
    nodes = list(graph.nodes.values())
    total = len(nodes)
    if total == 0:
        return {"score": 0, "grade": "F", "dimensions": {}}

    # ── Level distribution ────────────────────────────────────────────────
    levels: Dict[str, int] = Counter()
    for n in nodes:
        levels[n.level] += 1

    error_count = levels.get("error", 0) + levels.get("critical", 0) + levels.get("exception", 0)
    warning_count = levels.get("warning", 0)
    info_count = levels.get("info", 0)
    debug_count = levels.get("debug", 0)

    # Level balance: penalize if any single level is >80% of total
    max_level_pct = max(levels.values()) / total if total else 0
    level_balance_score = max(0, 100 - (max_level_pct - 0.5) * 200)
    level_balance_score = min(100, level_balance_score)

    # Error visibility: at least 5% of nodes should be error/critical
    error_pct = error_count / total if total else 0
    if error_pct >= 0.05:
        error_vis_score = 100
    elif error_pct >= 0.01:
        error_vis_score = 60 + (error_pct / 0.05) * 40
    elif error_pct > 0:
        error_vis_score = 30
    else:
        error_vis_score = 0  # Zero error nodes = zero visibility

    # ── Edge connectivity ─────────────────────────────────────────────────
    with_parents = sum(1 for n in nodes if n.call_parent_names)
    with_children = sum(1 for n in nodes if n.call_child_names)
    connected = sum(1 for n in nodes if n.call_parent_names or n.call_child_names)
    connectivity_pct = connected / total if total else 0
    edge_score = min(100, connectivity_pct * 150)  # 67% connected = 100

    # ── Function naming ───────────────────────────────────────────────────
    module_nodes = sum(1 for n in nodes if n.function == "<module>")
    named_pct = 1 - (module_nodes / total) if total else 0
    naming_score = named_pct * 100

    # ── Signature coverage ────────────────────────────────────────────────
    with_sig = sum(1 for n in nodes if n.signature is not None)
    sig_pct = with_sig / total if total else 0
    sig_score = sig_pct * 100

    # ── Tag diversity ─────────────────────────────────────────────────────
    all_tags: Counter = Counter()
    for n in nodes:
        for tag in n.semantic_tags:
            all_tags[tag] += 1
    # Good diversity = tags spread across many domains
    unique_tags = len(all_tags)
    tag_score = min(100, unique_tags * 12)  # 8+ unique tags = 100

    # ── Weighted composite ────────────────────────────────────────────────
    dimensions = {
        "level_balance": {"score": round(level_balance_score, 1), "weight": _WEIGHTS["level_balance"]},
        "error_visibility": {"score": round(error_vis_score, 1), "weight": _WEIGHTS["error_visibility"]},
        "edge_connectivity": {"score": round(edge_score, 1), "weight": _WEIGHTS["edge_connectivity"]},
        "function_naming": {"score": round(naming_score, 1), "weight": _WEIGHTS["function_naming"]},
        "signature_coverage": {"score": round(sig_score, 1), "weight": _WEIGHTS["signature_coverage"]},
        "tag_diversity": {"score": round(tag_score, 1), "weight": _WEIGHTS["tag_diversity"]},
    }

    composite = sum(d["score"] * d["weight"] for d in dimensions.values())
    composite = round(min(100, max(0, composite)), 1)

    if composite >= 90:
        grade = "A"
    elif composite >= 80:
        grade = "B+"
    elif composite >= 70:
        grade = "B"
    elif composite >= 60:
        grade = "B-"
    elif composite >= 50:
        grade = "C"
    elif composite >= 40:
        grade = "D"
    else:
        grade = "F"

    return {
        "score": composite,
        "grade": grade,
        "total_nodes": total,
        "levels": dict(levels),
        "error_count": error_count,
        "warning_count": warning_count,
        "connected": connected,
        "with_parents": with_parents,
        "with_children": with_children,
        "module_nodes": module_nodes,
        "with_sig": with_sig,
        "all_tags": all_tags,
        "unique_tags": unique_tags,
        "dimensions": dimensions,
    }


def _grade_color(grade: str) -> str:
    """Return a Rich color for the grade."""
    if grade.startswith("A"):
        return "bold green"
    elif grade.startswith("B"):
        return "bold cyan"
    elif grade.startswith("C"):
        return "bold yellow"
    else:
        return "bold red"


def _bar(value: float, max_val: float, width: int = 20, color: str = "cyan") -> Text:
    """Create a visual bar for a metric."""
    filled = int((value / max_val) * width) if max_val > 0 else 0
    filled = min(filled, width)
    bar_text = Text()
    bar_text.append("█" * filled, style=color)
    bar_text.append("░" * (width - filled), style="dim")
    return bar_text


def _render_report(graph: LogLoomGraph, health: dict, verbose: bool = False):
    """Render the full report to the console."""
    nodes = list(graph.nodes.values())
    total = health["total_nodes"]

    # ═══════════════════════════════════════════════════════════════════════
    # Header
    # ═══════════════════════════════════════════════════════════════════════
    grade = health["grade"]
    score = health["score"]
    grade_style = _grade_color(grade)

    header = Text()
    header.append(f"\n  {graph.project}", style="bold white")
    header.append(f"  Logging Health Report\n", style="dim")
    header.append(f"\n  Score: ", style="white")
    header.append(f"{score}", style=grade_style)
    header.append(f" / 100", style="dim")
    header.append(f"   Grade: ", style="white")
    header.append(f"{grade}", style=grade_style)
    header.append(f"\n  Nodes: ", style="white")
    header.append(f"{total}", style="bold")
    if graph.commit_sha:
        header.append(f"   Commit: ", style="white")
        header.append(f"{graph.commit_sha[:8]}", style="cyan")
    if graph.branch:
        header.append(f"   Branch: ", style="white")
        header.append(f"{graph.branch}", style="cyan")
    header.append("\n")

    console.print(Panel(header, title="[bold]🪵  LogLoom[/bold]", border_style="cyan", padding=(0, 1)))

    # ═══════════════════════════════════════════════════════════════════════
    # Score Breakdown
    # ═══════════════════════════════════════════════════════════════════════
    score_table = Table(
        title="Score Breakdown",
        box=box.ROUNDED,
        border_style="cyan",
        title_style="bold",
        show_header=True,
        header_style="bold",
    )
    score_table.add_column("Dimension", style="white", min_width=22)
    score_table.add_column("Score", justify="right", style="bold", min_width=6)
    score_table.add_column("Weight", justify="right", style="dim", min_width=6)
    score_table.add_column("", min_width=22)

    _dim_labels = {
        "level_balance": "Log Level Balance",
        "error_visibility": "Error Visibility",
        "edge_connectivity": "Edge Connectivity",
        "function_naming": "Function Naming",
        "signature_coverage": "Signature Coverage",
        "tag_diversity": "Tag Diversity",
    }

    for key, dim in health["dimensions"].items():
        s = dim["score"]
        color = "green" if s >= 80 else "yellow" if s >= 50 else "red"
        label = _dim_labels.get(key, key)
        score_table.add_row(
            label,
            f"{s:.0f}",
            f"{dim['weight']:.0%}",
            _bar(s, 100, width=20, color=color),
        )

    console.print(score_table)

    # ═══════════════════════════════════════════════════════════════════════
    # Level Distribution
    # ═══════════════════════════════════════════════════════════════════════
    level_table = Table(
        title="Log Level Distribution",
        box=box.ROUNDED,
        border_style="blue",
        title_style="bold",
    )
    level_table.add_column("Level", style="bold", min_width=10)
    level_table.add_column("Count", justify="right", min_width=6)
    level_table.add_column("Pct", justify="right", min_width=6)
    level_table.add_column("", min_width=30)

    level_order = ["critical", "error", "warning", "info", "debug", "log", "exception"]
    level_colors = {
        "critical": "bold red", "error": "red", "warning": "yellow",
        "info": "green", "debug": "dim", "log": "dim", "exception": "red",
    }

    for lvl in level_order:
        ct = health["levels"].get(lvl, 0)
        if ct == 0 and lvl not in ("critical", "error", "warning", "info", "debug"):
            continue
        pct = 100 * ct / total if total else 0
        color = level_colors.get(lvl, "white")
        level_table.add_row(
            Text(lvl, style=color),
            str(ct),
            f"{pct:.1f}%",
            _bar(ct, total, width=30, color=color.replace("bold ", "")),
        )

    console.print(level_table)

    # ═══════════════════════════════════════════════════════════════════════
    # Semantic Tag Surface
    # ═══════════════════════════════════════════════════════════════════════
    tags = health["all_tags"]
    if tags:
        tag_table = Table(
            title="Semantic Tag Surface",
            box=box.ROUNDED,
            border_style="magenta",
            title_style="bold",
        )
        tag_table.add_column("Tag", style="bold magenta", min_width=14)
        tag_table.add_column("Nodes", justify="right", min_width=6)
        tag_table.add_column("", min_width=25)

        max_tag = max(tags.values()) if tags else 1
        for tag, ct in tags.most_common(12):
            tag_table.add_row(tag, str(ct), _bar(ct, max_tag, width=25, color="magenta"))

        console.print(tag_table)

    # ═══════════════════════════════════════════════════════════════════════
    # Module Hotspots — Top modules by log density
    # ═══════════════════════════════════════════════════════════════════════
    modules: Dict[str, Dict] = {}
    for n in nodes:
        mod = n.module or "(unknown)"
        if mod not in modules:
            modules[mod] = {"total": 0, "error": 0, "warning": 0, "connected": 0, "named": 0}
        modules[mod]["total"] += 1
        if n.level in ("error", "critical", "exception"):
            modules[mod]["error"] += 1
        if n.level == "warning":
            modules[mod]["warning"] += 1
        if n.call_parent_names or n.call_child_names:
            modules[mod]["connected"] += 1
        if n.function != "<module>":
            modules[mod]["named"] += 1

    # Sort by total nodes descending
    sorted_modules = sorted(modules.items(), key=lambda x: -x[1]["total"])

    mod_table = Table(
        title="Top Modules by Log Density",
        box=box.ROUNDED,
        border_style="green",
        title_style="bold",
    )
    mod_table.add_column("Module", style="bold", max_width=45, no_wrap=True, overflow="ellipsis")
    mod_table.add_column("Nodes", justify="right", min_width=6)
    mod_table.add_column("Errors", justify="right", min_width=6)
    mod_table.add_column("Connected", justify="right", min_width=10)
    mod_table.add_column("Named", justify="right", min_width=6)

    for mod_name, stats in sorted_modules[:15]:
        conn_pct = 100 * stats["connected"] / stats["total"] if stats["total"] else 0
        name_pct = 100 * stats["named"] / stats["total"] if stats["total"] else 0
        err_style = "red" if stats["error"] > 0 else "dim"
        conn_style = "green" if conn_pct >= 50 else "yellow" if conn_pct > 0 else "dim"
        mod_table.add_row(
            mod_name,
            str(stats["total"]),
            Text(str(stats["error"]), style=err_style),
            Text(f"{stats['connected']}/{stats['total']} ({conn_pct:.0f}%)", style=conn_style),
            f"{stats['named']}/{stats['total']}",
        )

    console.print(mod_table)

    # ═══════════════════════════════════════════════════════════════════════
    # Blind Spots — Uninstrumented functions (from coverage)
    # ═══════════════════════════════════════════════════════════════════════
    if graph.coverage and graph.coverage.uninstrumented:
        blind_table = Table(
            title=f"Observability Blind Spots ({len(graph.coverage.uninstrumented)} uninstrumented functions)",
            box=box.ROUNDED,
            border_style="red",
            title_style="bold",
        )
        blind_table.add_column("Function", style="red", min_width=50)

        shown = 0
        for func in sorted(graph.coverage.uninstrumented)[:20]:
            blind_table.add_row(func)
            shown += 1

        remaining = len(graph.coverage.uninstrumented) - shown
        if remaining > 0:
            blind_table.add_row(f"... and {remaining} more", style="dim")

        console.print(blind_table)

    # ═══════════════════════════════════════════════════════════════════════
    # Recommendations
    # ═══════════════════════════════════════════════════════════════════════
    recs = []

    if health["error_count"] == 0:
        recs.append(("[bold red]CRITICAL[/bold red]", "Zero error-level log sites detected. Error paths are completely invisible at runtime."))
    elif health["error_count"] / total < 0.02:
        recs.append(("[yellow]WARNING[/yellow]", f"Only {health['error_count']} error nodes ({100*health['error_count']/total:.1f}%). Consider adding error logging to catch/except blocks."))

    if health["module_nodes"] > 0:
        recs.append(("[yellow]WARNING[/yellow]", f"{health['module_nodes']} nodes ({100*health['module_nodes']/total:.1f}%) have unresolved function names (<module>). These are likely inline callbacks or closures."))

    orphan_pct = 1 - (health["connected"] / total) if total else 0
    if orphan_pct > 0.5:
        recs.append(("[yellow]WARNING[/yellow]", f"{100*orphan_pct:.0f}% of nodes are orphans (no call-graph edges). This limits trace debugging utility."))

    sig_pct = health["with_sig"] / total if total else 0
    if sig_pct < 0.5:
        recs.append(("[dim]INFO[/dim]", f"Only {100*sig_pct:.0f}% of nodes have function signatures. Signatures help LLMs understand parameter context."))

    if not recs:
        recs.append(("[bold green]✅[/bold green]", "No critical issues detected. Logging instrumentation looks healthy."))

    rec_table = Table(
        title="Recommendations",
        box=box.ROUNDED,
        border_style="yellow",
        title_style="bold",
        show_header=False,
    )
    rec_table.add_column("", min_width=10)
    rec_table.add_column("", min_width=60)

    for severity, msg in recs:
        rec_table.add_row(severity, msg)

    console.print(rec_table)

    # ═══════════════════════════════════════════════════════════════════════
    # Footer
    # ═══════════════════════════════════════════════════════════════════════
    console.print(
        f"\n  [dim]Built at {graph.built_at} · Schema v{graph.schema_version} · "
        f"Run [bold]logloom report --help[/bold] for options[/dim]\n"
    )


@click.command()
@click.option("--graph-path", default="logloom-graph.json", help="Path to the LogLoom graph JSON.")
@click.option("--min-score", type=float, default=None, help="Minimum health score (0-100). Exit 1 if below threshold.")
@click.option("--verbose", is_flag=True, help="Show additional details and blind spots.")
def report(graph_path: str, min_score: Optional[float], verbose: bool):
    """Generate a codebase logging health report.

    Analyzes the LogLoom graph to produce a comprehensive assessment of
    logging instrumentation quality. No Elasticsearch or live logs required.

    Can be used as a CI/CD quality gate:

        logloom report --min-score 60
    """
    g = load_graph(Path(graph_path))
    if not g:
        console.print(f"[red]❌ Could not load graph from {graph_path}[/red]")
        console.print("Run [bold cyan]logloom build --source <path>[/bold cyan] first.")
        raise SystemExit(1)

    if not g.nodes:
        console.print("[yellow]⚠️  Graph has no nodes. Nothing to report.[/yellow]")
        raise SystemExit(0)

    health = _compute_health(g)
    _render_report(g, health, verbose=verbose)

    # CI/CD gate
    if min_score is not None and health["score"] < min_score:
        console.print(
            f"\n[bold red]❌ Health score {health['score']} is below minimum threshold {min_score}[/bold red]"
        )
        raise SystemExit(1)
