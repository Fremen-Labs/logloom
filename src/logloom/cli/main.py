import click
from .build import build
from .init import init

@click.group()
@click.version_option()
def cli():
    """LogLoom — Weave your codebase into every log line."""
    pass

cli.add_command(build)
cli.add_command(init)

if __name__ == "__main__":
    cli()