"""Command line interface and composition root for pr-bench.

This is the only place allowed to know every layer: use cases and adapters are wired
together here as they are added.
"""

from pathlib import Path
from typing import Annotated

import typer

from pr_inspector_benchmark import __version__
from pr_inspector_benchmark.domain.entities import is_valid_case_id
from pr_inspector_benchmark.infrastructure.fixture_builder import FixtureBuildError, render_skeleton
from pr_inspector_benchmark.infrastructure.git_change_source import GitChangeSource

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


def create_change_source() -> GitChangeSource:
    """Composition root: the adapter that fetches a commit and reverses its diff."""
    return GitChangeSource()


def _fail(message: str) -> typer.Exit:
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(code=2)


@app.command("build-fixture")
def build_fixture(
    repo: Annotated[str, typer.Option("--repo", help="GitHub repository, owner/name.")],
    commit: Annotated[str, typer.Option("--commit", help="Fix commit (or PR merge commit).")],
    fixture_id: Annotated[str, typer.Option("--id", help="Fixture id: a lowercase slug.")],
    license_id: Annotated[str, typer.Option("--license", help="SPDX license id of the repo.")],
    base: Annotated[
        str | None, typer.Option(help="Commit before the change; default: first parent.")
    ] = None,
    pr: Annotated[int | None, typer.Option(help="Pull request number, for provenance.")] = None,
    advisory: Annotated[str | None, typer.Option(help="Advisory id, e.g. GHSA-xxxx.")] = None,
    output_dir: Annotated[Path, typer.Option(help="Where to write the fixture.")] = Path(
        "fixtures"
    ),
    force: Annotated[bool, typer.Option(help="Overwrite an existing fixture.")] = False,
    keep_comments: Annotated[
        bool, typer.Option(help="Keep the fix's explanatory comments in the diff (they leak it).")
    ] = False,
    also_drop: Annotated[
        str | None, typer.Option(help="Also drop deleted lines matching this regex (e.g. prose).")
    ] = None,
) -> None:
    """Write a fixture skeleton: the reversed fix, with TODO placeholders to fill in."""
    if not is_valid_case_id(fixture_id):
        raise _fail(f"id must be a lowercase slug (letters, digits, '-' and '_'): {fixture_id!r}")
    target = output_dir / f"{fixture_id}.json"
    if target.exists() and not force:
        raise _fail(f"{target} already exists; pass --force to overwrite it")
    try:
        change = create_change_source().fetch_reversed_change(
            repo, commit, base, drop_comments=not keep_comments, also_drop=also_drop
        )
    except FixtureBuildError as exc:
        raise _fail(str(exc)) from exc

    text = render_skeleton(
        fixture_id=fixture_id,
        repository=repo,
        license_id=license_id,
        commit=commit,
        change=change,
        pull_request=pr,
        advisory=advisory,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    typer.echo(f"wrote {target} ({len(change.files)} source file(s))")
    if change.dropped_lines:
        typer.echo(f"dropped {change.dropped_lines} explanatory line(s) from the old side")
    typer.echo("Fill in every TODO field, then check it with the loader.")
