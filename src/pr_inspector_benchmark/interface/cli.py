"""Command line interface and composition root for pr-bench.

This is the only place allowed to know every layer: use cases and adapters are wired
together here as they are added.
"""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from pr_inspector_benchmark import __version__
from pr_inspector_benchmark.application.use_cases.run_benchmark import RunBenchmarkUseCase
from pr_inspector_benchmark.domain.entities import is_valid_case_id
from pr_inspector_benchmark.domain.exceptions import FixtureLoadError
from pr_inspector_benchmark.domain.protocols import ReviewerPort
from pr_inspector_benchmark.domain.runs import RunInfo
from pr_inspector_benchmark.infrastructure.fixture_builder import FixtureBuildError, render_skeleton
from pr_inspector_benchmark.infrastructure.fixture_loader import (
    JsonFixtureLoader,
    SubsetFixtureLoader,
)
from pr_inspector_benchmark.infrastructure.git_change_source import GitChangeSource
from pr_inspector_benchmark.infrastructure.pr_inspector_reviewer import (
    ReviewerSettings,
    build_reviewer,
    default_system_prompt,
    is_local_endpoint,
    prompt_fingerprint,
    system_prompt,
)
from pr_inspector_benchmark.infrastructure.run_store import RunStoreError, read_run, write_run
from pr_inspector_benchmark.infrastructure.token_estimate import estimate_input_tokens
from pr_inspector_benchmark.interface.comparison import build_comparison, to_markdown, to_rich
from pr_inspector_benchmark.interface.formatting import case_line, run_summary

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


def _read_prompt(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _fail(f"cannot read prompt file {path}: {exc.strerror}") from exc
    if not text.strip():
        raise _fail(f"prompt file {path} is empty")
    return text


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


def create_reviewer(settings: ReviewerSettings) -> ReviewerPort:
    """Composition root: the reviewer under test."""
    return build_reviewer(settings)


def _read_api_key(variable: str | None, local: bool) -> str | None:
    """The key comes only from a named environment variable, never from the command line."""
    if variable is None:
        if local:
            return "ollama"  # a local server ignores the key but the client insists on one
        raise _fail(
            "a remote endpoint needs --api-key-env <VARIABLE>, the name of the environment "
            "variable that holds the key"
        )
    value = os.environ.get(variable, "")
    if not value:
        raise _fail(f"environment variable {variable} is not set or is empty")
    return value


@app.command("run")
def run(
    label: Annotated[
        str, typer.Option("--label", help="Name of this run and of its results file.")
    ],
    model: Annotated[str, typer.Option("--model", help="The model to benchmark.")],
    base_url: Annotated[
        str, typer.Option("--base-url", help="OpenAI-compatible endpoint. Always explicit.")
    ],
    api_key_env: Annotated[
        str | None,
        typer.Option("--api-key-env", help="Name of the variable that holds the key, not the key."),
    ] = None,
    fixtures: Annotated[Path, typer.Option(help="Directory of fixtures.")] = Path("fixtures"),
    output_dir: Annotated[Path, typer.Option(help="Where to save the run.")] = Path("results"),
    only: Annotated[
        list[str] | None, typer.Option("--only", help="Run only this fixture id. Repeatable.")
    ] = None,
    line_tolerance: Annotated[
        int, typer.Option(min=0, help="Lines of slack around an expected window.")
    ] = 0,
    timeout: Annotated[
        float, typer.Option(min=1, help="Seconds before a request gives up.")
    ] = 180.0,
    price_in: Annotated[
        float | None, typer.Option(min=0, help="USD per million input tokens.")
    ] = None,
    price_out: Annotated[
        float | None, typer.Option(min=0, help="USD per million output tokens.")
    ] = None,
    prompt_file: Annotated[
        Path | None,
        typer.Option(help="Use this file as the system prompt instead of pr-inspector's default."),
    ] = None,
    withhold_model: Annotated[
        bool,
        typer.Option(help="Save 'withheld' in place of the model name, for published results."),
    ] = False,
    force: Annotated[bool, typer.Option(help="Overwrite an existing results file.")] = False,
) -> None:
    """Review every fixture with one model and save the run."""
    local = is_local_endpoint(base_url)
    prompt_text = _read_prompt(prompt_file) if prompt_file else default_system_prompt()
    shown_model = "withheld" if withhold_model else model
    try:
        info = RunInfo(
            label=label,
            model=shown_model,
            endpoint="local" if local else "remote",
            started_at=datetime.now(UTC).isoformat(timespec="seconds"),
            line_tolerance=line_tolerance,
            # A local model costs nothing. A remote one with no price given has an unknown cost.
            price_in=0.0 if local and price_in is None else price_in,
            price_out=0.0 if local and price_out is None else price_out,
            prompt_sha=prompt_fingerprint(prompt_text),
        )
    except ValueError as exc:
        raise _fail(str(exc)) from exc

    target = output_dir / f"{label}.json"
    if target.exists() and not force:
        raise _fail(f"{target} already exists; pass --force to overwrite it")
    api_key = _read_api_key(api_key_env, local)

    loader = JsonFixtureLoader(fixtures)
    if only:
        loader = SubsetFixtureLoader(loader, only)
    reviewer = create_reviewer(
        ReviewerSettings(model=model, base_url=base_url, api_key=api_key, timeout=timeout)
    )
    typer.echo(f"{label}: reviewing with {shown_model} on a {info.endpoint} endpoint")
    use_case = RunBenchmarkUseCase(loader, reviewer, line_tolerance=line_tolerance)
    try:
        cases = loader.load_all()
        estimates = {case.id: estimate_input_tokens(case.diff) for case in cases}
        with system_prompt(prompt_text):
            result = use_case.execute(
                on_case=lambda n, total, r: typer.echo(case_line(n, total, r))
            )
    except FixtureLoadError as exc:
        raise _fail(str(exc)) from exc

    billed = write_run(target, info, result, estimates)
    typer.echo(run_summary(info, result, str(target), billed))


@app.command("compare")
def compare(
    files: Annotated[list[Path], typer.Argument(help="Result files written by `pr-bench run`.")],
    markdown: Annotated[
        Path | None, typer.Option("--markdown", help="Also write the tables as Markdown.")
    ] = None,
    price_in: Annotated[
        float | None,
        typer.Option(min=0, help="Reprice every run: USD per million input tokens."),
    ] = None,
    price_out: Annotated[
        float | None,
        typer.Option(min=0, help="Reprice every run: USD per million output tokens."),
    ] = None,
) -> None:
    """Put saved runs side by side."""
    try:
        runs = [read_run(path) for path in files]
    except RunStoreError as exc:
        raise _fail(str(exc)) from exc
    labels = [run.label for run in runs]
    if len(set(labels)) != len(labels):
        raise _fail(
            f"two of the runs have the same label, so their columns would be ambiguous: {labels}"
        )

    if (price_in is None) != (price_out is None):
        raise _fail("give both --price-in and --price-out, or neither")
    comparison = build_comparison(runs, price_in=price_in, price_out=price_out)
    console = Console()
    for table in to_rich(comparison):
        console.print(table)
    for note in comparison.notes:
        typer.echo(note)
    if markdown is not None:
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(to_markdown(comparison), encoding="utf-8")
        typer.echo(f"wrote {markdown}")
