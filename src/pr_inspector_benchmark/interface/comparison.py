"""Puts saved runs side by side, as terminal tables or as Markdown.

The tables are built once, as plain data, so the terminal and the Markdown cannot disagree.
A value that could not be computed is ``n/a`` or ``unknown``, and a failed fixture is shown as
failed, never as a wrong answer.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from rich.markup import escape
from rich.table import Table

from pr_inspector_benchmark.domain.runs import billed_input_tokens
from pr_inspector_benchmark.infrastructure.run_store import CaseRecord, RunRecord
from pr_inspector_benchmark.interface.formatting import duration, money, percent

CONTEXTS = ("in_diff", "removed_check", "needs_context")
Row = tuple[str, tuple[str, ...]]


@dataclass(frozen=True)
class Comparison:
    labels: tuple[str, ...]
    summary: tuple[Row, ...]
    fixtures: tuple[Row, ...]
    notes: tuple[str, ...]


def _fraction(found: int, expected: int) -> str:
    return f"{found}/{expected} ({percent(found / expected if expected else None)})"


def _context_cell(run: RunRecord, context: str) -> str:
    tally = run.summary.recall_by_context.get(context)
    if tally is None or tally.expected == 0:
        return "-"
    return _fraction(tally.found, tally.expected)


def _mean_time(run: RunRecord) -> str:
    mean = run.totals.mean_latency_ms
    return "n/a" if mean is None else duration(mean)


def _billed(run: RunRecord) -> int:
    return billed_input_tokens(
        run.endpoint, run.totals.input_tokens, run.totals.input_tokens_estimated
    )


def _cost(run: RunRecord, price_in: float | None, price_out: float | None) -> float | None:
    """The run's stored cost, or the cost at the given prices applied to its saved tokens."""
    if price_in is None or price_out is None:
        return run.totals.cost_usd
    return (_billed(run) * price_in + run.totals.output_tokens * price_out) / 1_000_000


def _summary_rows(
    runs: Sequence[RunRecord], price_in: float | None = None, price_out: float | None = None
) -> tuple[Row, ...]:
    def row(name: str, cell) -> Row:
        return name, tuple(cell(run) for run in runs)

    rows = [
        row("model", lambda r: r.model),
        row("endpoint", lambda r: r.endpoint),
        row("fixtures scored", lambda r: f"{r.summary.cases} ({r.totals.failed_cases} failed)"),
        row("risk exact", lambda r: percent(r.summary.risk_accuracy)),
        row("risk within one level", lambda r: percent(r.summary.risk_near_accuracy)),
        row("issues found", lambda r: _fraction(r.summary.found_issues, r.summary.expected_issues)),
        row("precision", lambda r: percent(r.summary.precision)),
        row("false alarms", lambda r: str(r.summary.false_positives)),
        row(
            "controls flagged",
            lambda r: f"{r.summary.controls_with_reports}/{r.summary.control_cases}",
        ),
    ]
    rows += [row(f"recall: {c}", lambda r, c=c: _context_cell(r, c)) for c in CONTEXTS]
    rows += [
        row("tokens in (cost basis)", lambda r: f"{_billed(r):,}"),
        row("tokens out", lambda r: f"{r.totals.output_tokens:,}"),
        row("mean time per fixture", lambda r: _mean_time(r)),
        row("cost", lambda r: money(_cost(r, price_in, price_out))),
    ]  # fmt: skip
    return tuple(rows)


def _case_cell(case: CaseRecord) -> str:
    if case.error is not None:
        return "FAILED"
    risk = f"{case.expected_risk}->{case.predicted_risk}"
    found = case.expected_found or []
    detail = f"{sum(found)}/{len(found)}" if found else "control"
    return f"{risk} {detail} fa{case.false_positives}"


def build_comparison(
    runs: Sequence[RunRecord], price_in: float | None = None, price_out: float | None = None
) -> Comparison:
    """Side-by-side tables for one or more runs.

    The per-fixture table covers the fixtures every run has; the summary is each run's own.
    """
    by_id = [{case.id: case for case in run.cases} for run in runs]
    shared = [case.id for case in runs[0].cases if all(case.id in ids for ids in by_id)]
    fixtures = tuple((fid, tuple(_case_cell(ids[fid]) for ids in by_id)) for fid in shared)

    notes = [
        "fa = false alarms: reports that match no expected issue. n/a means nothing was countable."
    ]
    if any(run.endpoint == "remote" for run in runs):
        notes.append(
            "Remote runs are priced on estimated input tokens, because their reported counts "
            "include tokens that were never sent."
        )
    if price_in is not None:
        notes.append("Costs are repriced from the saved token counts at the prices given.")
    if any(len(ids) != len(shared) for ids in by_id):
        notes.append(
            f"The runs do not cover the same fixtures: the per-fixture table shows the "
            f"{len(shared)} that every run has, while the summary covers each run's own."
        )
    if len({run.line_tolerance for run in runs}) > 1:
        notes.append(
            "The runs used different line tolerances, so their recall is not directly comparable."
        )
    return Comparison(
        labels=tuple(run.label for run in runs),
        summary=_summary_rows(runs, price_in, price_out),
        fixtures=fixtures,
        notes=tuple(notes),
    )  # fmt: skip


def _markdown_table(first_column: str, labels: Sequence[str], rows: Sequence[Row]) -> str:
    header = f"| {first_column} | " + " | ".join(f"`{label}`" for label in labels) + " |"
    divider = "|---|" + "---|" * len(labels)
    lines = [header, divider]
    lines += [f"| {name} | " + " | ".join(cells) + " |" for name, cells in rows]
    return "\n".join(lines)


def to_markdown(comparison: Comparison) -> str:
    notes = "\n".join(f"- {note}" for note in comparison.notes)
    return (
        "## Summary\n\n"
        + _markdown_table("", comparison.labels, comparison.summary)
        + "\n\n## Per fixture\n\n"
        + _markdown_table("fixture", comparison.labels, comparison.fixtures)
        + f"\n\n{notes}\n"
    )


def _rich_table(title: str, first_column: str, labels: Sequence[str], rows: Sequence[Row]) -> Table:
    table = Table(title=title, title_justify="left")
    table.add_column(first_column, no_wrap=True)
    for label in labels:
        table.add_column(escape(label), no_wrap=True)
    for name, cells in rows:
        table.add_row(escape(name), *(escape(cell) for cell in cells))
    return table


def to_rich(comparison: Comparison) -> list[Table]:
    return [
        _rich_table("Summary", "", comparison.labels, comparison.summary),
        _rich_table("Per fixture", "fixture", comparison.labels, comparison.fixtures),
    ]
