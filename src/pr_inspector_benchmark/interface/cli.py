"""Command line interface and composition root for pr-bench.

This is the only place allowed to know every layer: use cases and adapters are wired
together here as they are added.
"""

from typing import Annotated

import typer

from pr_inspector_benchmark import __version__

app = typer.Typer(
    name="pr-bench",
    help="Benchmark pr-inspector across models on real historical code changes.",
    add_completion=False,
    no_args_is_help=True,
)


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"pr-bench version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-v",
            help="Show version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """Benchmark pr-inspector across models on real historical code changes."""
