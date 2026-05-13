import click
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

console = Console()

@click.command()
@click.option("--force", is_flag=True, help="Overwrite existing configuration files.")
def init(force: bool):
    """Initialize LogLoom in the current project."""
    console.print(Panel.fit("[bold blue]LogLoom Setup[/bold blue]", subtitle="v0.1.0"))
    
    cwd = Path.cwd()
    ignore_file = cwd / ".logloomignore"
    rc_file = cwd / ".logloomrc.toml"

    # Interactive project name prompt
    project_name = click.prompt("What is the name of your project?", default=cwd.name)

    if not ignore_file.exists() or force:
        ignore_file.write_text("# Ignore standard python artifacts\n**/__pycache__/**\n.venv/\nvenv/\n.env\n")
        console.print("[green]✔[/green] Created [bold].logloomignore[/bold]")
    else:
        console.print("[yellow]![/yellow] [bold].logloomignore[/bold] already exists. Use --force to overwrite.")

    if not rc_file.exists() or force:
        rc_file.write_text(f'[logloom]\nproject_name = "{project_name}"\n')
        console.print("[green]✔[/green] Created [bold].logloomrc.toml[/bold]")
    else:
        console.print("[yellow]![/yellow] [bold].logloomrc.toml[/bold] already exists. Use --force to overwrite.")

    console.print("\n[bold green]🎉 LogLoom initialized successfully![/bold green]")
    console.print("Run [bold cyan]logloom build --source src/[/bold cyan] to generate your first graph.")