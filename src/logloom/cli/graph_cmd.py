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


@graph.command()
@click.option("--graph-path", default="logloom-graph.json", help="Path to graph JSON.")
def imports(graph_path: str):
    """Show the module import relationships as a tree."""
    g = load_graph(Path(graph_path))
    if not g:
        console.print("[red]❌ Could not load graph.[/red]")
        return

    if not g.imports:
        console.print("[yellow]No imports recorded in the graph.[/yellow]")
        return

    tree = Tree("[bold cyan]Import Dependency Tree[/bold cyan]")
    for mod, imps in sorted(g.imports.items()):
        branch = tree.add(f"[bold]{mod}[/bold]")
        for imp in sorted(imps):
            branch.add(f"[dim]{imp}[/dim]")
    console.print(tree)


@graph.command()
@click.option("--graph-path", default="logloom-graph.json", help="Path to graph JSON.")
def models(graph_path: str):
    """Show data models, schemas, and fields extracted from code."""
    g = load_graph(Path(graph_path))
    if not g:
        console.print("[red]❌ Could not load graph.[/red]")
        return

    if not g.models:
        console.print("[yellow]No data models extracted in the graph.[/yellow]")
        return

    table = Table(title="Extracted Data Models", border_style="dim")
    table.add_column("Model Name", style="bold cyan")
    table.add_column("File:Line", style="dim")
    table.add_column("Base Classes")
    table.add_column("Fields")

    for key, model in sorted(g.models.items()):
        bases = ", ".join(model.base_classes) if model.base_classes else "None"
        fields_str = []
        for field in model.fields:
            req = "" if field.is_required else "?"
            fields_str.append(f"{field.name}{req}: {field.type_hint}")
        table.add_row(
            model.name,
            f"{model.file}:{model.line}",
            bases,
            ", ".join(fields_str) if fields_str else "None",
        )
    console.print(table)


@graph.command()
@click.option("--graph-path", default="logloom-graph.json", help="Path to graph JSON.")
@click.option("--output", default="logloom-graph.html", help="Path to write the HTML visualization.")
def viz(graph_path: str, output: str):
    """Generate an interactive HTML visualization of the call graph."""
    g = load_graph(Path(graph_path))
    if not g:
        console.print("[red]❌ Could not load graph.[/red]")
        return

    try:
        with open(graph_path, "r", encoding="utf-8") as f:
            graph_json_str = f.read()
    except Exception as e:
        console.print(f"[red]❌ Failed to read graph JSON: {e}[/red]")
        return

    html_template = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>LogLoom Graph Visualization</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        body {
            margin: 0; padding: 0;
            background-color: #0f172a; color: #f1f5f9;
            font-family: system-ui, -apple-system, sans-serif;
            overflow: hidden;
        }
        #canvas { width: 100vw; height: 100vh; display: block; }
        .node { stroke: #1e293b; stroke-width: 2px; cursor: pointer; }
        .node:hover { stroke: #f1f5f9; stroke-width: 3px; }
        .link { stroke: #475569; stroke-opacity: 0.4; stroke-width: 1.5px; fill: none; }
        .link.active { stroke: #38bdf8; stroke-opacity: 0.9; stroke-width: 2.5px; }
        .tooltip {
            position: absolute; background: rgba(15, 23, 42, 0.9);
            border: 1px solid #334155; padding: 10px; border-radius: 8px;
            pointer-events: none; font-size: 12px; display: none; z-index: 10;
        }
        #sidebar {
            position: absolute; top: 20px; left: 20px; width: 350px;
            max-height: calc(100vh - 40px); background: rgba(30, 41, 59, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.1); backdrop-filter: blur(12px);
            border-radius: 12px; padding: 20px; overflow-y: auto; z-index: 5;
        }
        #search-box {
            width: 100%; background: rgba(15, 23, 42, 0.6); border: 1px solid #475569;
            padding: 8px 12px; border-radius: 6px; color: #f1f5f9; margin-bottom: 15px;
            box-sizing: border-box; outline: none;
        }
        #search-box:focus { border-color: #38bdf8; }
        h2 { margin-top: 0; font-size: 18px; border-bottom: 1px solid #334155; padding-bottom: 8px; color: #38bdf8; }
        .detail-item { margin-bottom: 12px; }
        .detail-label { font-size: 10px; text-transform: uppercase; color: #94a3b8; }
        .detail-value { font-size: 14px; word-break: break-all; }
        .tag { display: inline-block; background: #0369a1; color: #e0f2fe; padding: 2px 6px; border-radius: 4px; font-size: 11px; margin-right: 4px; }
    </style>
</head>
<body>
    <div id="sidebar">
        <h2>LogLoom Graph</h2>
        <input type="text" id="search-box" placeholder="Search function, module, message...">
        <div id="details">
            <p style="color: #94a3b8; font-style: italic;">Click a node to view runtime log metadata, lexical context, parameter signatures, and call parents/children.</p>
        </div>
    </div>
    <div class="tooltip" id="tooltip"></div>
    <svg id="canvas"></svg>

    <script>
        const graphData = GRAPH_DATA_PLACEHOLDER;
        
        const nodes = Object.values(graphData.nodes).map(n => ({
            id: n.node_id,
            name: n.function,
            module: n.module,
            file: n.file,
            line: n.line,
            level: n.level,
            message: n.message_template,
            tags: n.semantic_tags || [],
            call_parents: n.call_parents || [],
            call_children: n.call_children || [],
            signature: n.signature
        }));

        const nodeMap = new Map(nodes.map(n => [n.id, n]));
        const links = [];
        nodes.forEach(sourceNode => {
            sourceNode.call_children.forEach(targetId => {
                if (nodeMap.has(targetId)) {
                    links.push({ source: sourceNode.id, target: targetId });
                }
            });
        });

        const svg = d3.select("#canvas");
        const width = window.innerWidth;
        const height = window.innerHeight;
        
        const gContainer = svg.append("g");
        
        svg.call(d3.zoom().on("zoom", (event) => {
            gContainer.attr("transform", event.transform);
        }));

        svg.append("defs").append("marker")
            .attr("id", "arrow")
            .attr("viewBox", "0 -5 10 10")
            .attr("refX", 20)
            .attr("refY", 0)
            .attr("markerWidth", 6)
            .attr("markerHeight", 6)
            .attr("orient", "auto")
            .append("path")
            .attr("d", "M0,-5L10,0L0,5")
            .attr("fill", "#475569");

        const simulation = d3.forceSimulation(nodes)
            .force("link", d3.forceLink(links).id(d => d.id).distance(100))
            .force("charge", d3.forceManyBody().strength(-150))
            .force("center", d3.forceCenter(width / 2, height / 2))
            .force("collision", d3.forceCollide().radius(25));

        const link = gContainer.append("g")
            .selectAll("path")
            .data(links)
            .enter().append("path")
            .attr("class", "link")
            .attr("marker-end", "url(#arrow)");

        const node = gContainer.append("g")
            .selectAll("circle")
            .data(nodes)
            .enter().append("circle")
            .attr("class", "node")
            .attr("r", d => 8 + (d.call_parents.length + d.call_children.length) * 1.5)
            .attr("fill", d => {
                if (d.file.endsWith(".py")) return "#38bdf8";
                if (d.file.endsWith(".go")) return "#22d3ee";
                if (d.file.endsWith(".ts") || d.file.endsWith(".tsx") || d.file.endsWith(".js")) return "#facc15";
                return "#a78bfa";
            })
            .call(d3.drag()
                .on("start", dragstarted)
                .on("drag", dragged)
                .on("end", dragended));

        const tooltip = d3.select("#tooltip");
        const detailsContainer = d3.select("#details");

        node.on("mouseover", (event, d) => {
            tooltip.style("display", "block")
                .html(`<strong>${d.module}.${d.name}()</strong><br><span style="color:#94a3b8">${d.file}:${d.line}</span><br><em style="color:#38bdf8">"${d.message}"</em>`)
                .style("left", (event.pageX + 15) + "px")
                .style("top", (event.pageY - 15) + "px");
        })
        .on("mousemove", (event) => {
            tooltip.style("left", (event.pageX + 15) + "px")
                .style("top", (event.pageY - 15) + "px");
        })
        .on("mouseout", () => {
            tooltip.style("display", "none");
        })
        .on("click", (event, d) => {
            link.classed("active", l => l.source.id === d.id || l.target.id === d.id);
            
            let sigHtml = "None";
            if (d.signature) {
                const params = d.signature.parameters || [];
                const paramsStr = params.map(p => `${p.name}${p.type_hint ? ': ' + p.type_hint : ''}`).join(", ");
                const decorators = d.signature.decorators || [];
                const decsStr = decorators.map(dec => `@${dec}<br>`).join("");
                sigHtml = `<pre style="background:#0f172a; padding:6px; border-radius:4px; margin:0; font-size:11px;">${decsStr}${d.signature.is_async ? 'async ' : ''}def ${d.name}(${paramsStr}) -> ${d.signature.return_type || 'None'}</pre>`;
            }

            const tagsHtml = d.tags.map(t => `<span class="tag">${t}</span>`).join("");
            detailsContainer.html(`
                <div class="detail-item">
                    <div class="detail-label">Node ID</div>
                    <div class="detail-value" style="font-family:monospace; color:#38bdf8">${d.id}</div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">File & Line</div>
                    <div class="detail-value">${d.file}:${d.line}</div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">Module / Package</div>
                    <div class="detail-value" style="font-weight:bold">${d.module}</div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">Function Signature</div>
                    <div class="detail-value">${sigHtml}</div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">Log Template</div>
                    <div class="detail-value" style="color:#e2e8f0; font-style:italic">"${d.message}"</div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">Semantic Tags</div>
                    <div class="detail-value">${tagsHtml || 'None'}</div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">Call Hierarchy</div>
                    <div style="font-size:12px; margin-top:4px;">
                        <strong>Parents calling this:</strong> ${d.call_parents.length ? d.call_parents.map(p => '<br>• ' + p).join("") : 'None'}
                        <br><br>
                        <strong>Children called:</strong> ${d.call_children.length ? d.call_children.map(c => '<br>• ' + c).join("") : 'None'}
                    </div>
                </div>
            `);
        });

        d3.select("#search-box").on("input", function() {
            const val = this.value.toLowerCase();
            node.style("opacity", d => {
                if (!val) return 1.0;
                return (d.name.toLowerCase().includes(val) || 
                        d.module.toLowerCase().includes(val) || 
                        d.message.toLowerCase().includes(val)) ? 1.0 : 0.15;
            });
            link.style("opacity", d => {
                if (!val) return 1.0;
                return (d.source.name.toLowerCase().includes(val) || d.target.name.toLowerCase().includes(val)) ? 1.0 : 0.1;
            });
        });

        simulation.on("tick", () => {
            link.attr("d", d => {
                const dx = d.target.x - d.source.x,
                      dy = d.target.y - d.source.y,
                      dr = Math.sqrt(dx * dx + dy * dy);
                return `M${d.source.x},${d.source.y}A${dr},${dr} 0 0,1 ${d.target.x},${d.target.y}`;
            });

            node
                .attr("cx", d => d.x)
                .attr("cy", d => d.y);
        });

        function dragstarted(event, d) {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x; d.fy = d.y;
        }

        function dragged(event, d) {
            d.fx = event.x; d.fy = event.y;
        }

        function dragended(event, d) {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null; d.fy = null;
        }

        window.addEventListener("resize", () => {
            const w = window.innerWidth;
            const h = window.innerHeight;
            svg.attr("width", w).attr("height", h);
            simulation.force("center", d3.forceCenter(w / 2, h / 2)).restart();
        });
    </script>
</body>
</html>"""

    html_content = html_template.replace("GRAPH_DATA_PLACEHOLDER", graph_json_str)

    try:
        out_path = Path(output)
        out_path.write_text(html_content, encoding="utf-8")
        console.print(f"[green]✨ Generated interactive visualization: [bold]{output}[/bold][/green]")
    except Exception as e:
        console.print(f"[red]❌ Failed to write visualization: {e}[/red]")


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
