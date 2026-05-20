import click
from .build import build
from .init import init
from .graph_cmd import graph
from .lint import lint
from .diff_cmd import diff
from .es_cmd import es
from .report import report

@click.group()
@click.version_option()
def cli():
    """LogLoom — Weave your codebase into every log line."""
    pass

cli.add_command(build)
cli.add_command(init)
cli.add_command(graph)
cli.add_command(lint)
cli.add_command(diff)
cli.add_command(es)
cli.add_command(report)

if __name__ == "__main__":
    cli()