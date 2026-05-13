import click
from pathlib import Path

@click.command()
@click.option("--force", is_flag=True)
def init(force: bool):
    """Initialize LogLoom in the current project."""
    cwd = Path.cwd()
    ignore_file = cwd / ".logloomignore"
    rc_file = cwd / ".logloomrc.toml"

    if not ignore_file.exists() or force:
        ignore_file.write_text("# Add patterns to ignore\n**/__pycache__/**\n")
        click.echo("✅ Created .logloomignore")

    if not rc_file.exists() or force:
        rc_file.write_text('[logloom]\nproject_name = "my-app"\n')
        click.echo("✅ Created .logloomrc.toml")

    click.echo("🎉 LogLoom initialized!")