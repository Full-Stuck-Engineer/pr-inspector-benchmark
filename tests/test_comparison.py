"""Tests for the side-by-side comparison of saved runs."""

import io
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from pr_inspector_benchmark.domain.entities import ContextNeeded, RiskLevel
from pr_inspector_benchmark.domain.results import CaseResult, CaseScore, RunResult, Telemetry
from pr_inspector_benchmark.domain.runs import RunInfo
from pr_inspector_benchmark.domain.scoring import summarize
from pr_inspector_benchmark.infrastructure.run_store import RunRecord, read_run, write_run
from pr_inspector_benchmark.interface.cli import app
from pr_inspector_benchmark.interface.comparison import build_comparison, to_markdown, to_rich

runner = CliRunner()


def scored(case_id, found, reported, matched, expected, predicted, context=ContextNeeded.IN_DIFF):
    score = CaseScore(case_id, context, expected, predicted, found, reported, matched)
    return CaseResult(case_id, score=score, telemetry=Telemetry("m", 1000, 100, 2000.0))


def run_record(tmp_path: Path, label: str, cases, **info_options) -> RunRecord:
    scores = [case.score for case in cases if case.score is not None]
    info = RunInfo(
        label, info_options.pop("model", "some-model"), info_options.pop("endpoint", "remote"),
        "2026-11-23T20:00:00+00:00", **info_options,
    )  # fmt: skip
    path = tmp_path / f"{label}.json"
    write_run(
        path,
        info,
        RunResult(cases=tuple(cases), summary=summarize(scores)),
        {c.case_id: 1000 for c in cases},
    )
    return read_run(path)


def standard_cases(*, bug_found: bool = True):
    return [
        scored("bug-a", (bug_found,), 2, 1 if bug_found else 0, RiskLevel.HIGH, RiskLevel.HIGH),
        scored(
            "bug-b",
            (True, False),
            1,
            1,
            RiskLevel.CRITICAL,
            RiskLevel.MEDIUM,
            ContextNeeded.NEEDS_CONTEXT,
        ),  # fmt: skip
        scored("control", (), 1, 0, RiskLevel.LOW, RiskLevel.LOW),
        CaseResult("slow-one", error="request timed out"),
    ]


def cell(rows, name: str, column: int = 0) -> str:
    return next(values for row_name, values in rows if row_name == name)[column]


def test_the_summary_has_one_column_per_run(tmp_path: Path):
    runs = [run_record(tmp_path, "local", standard_cases(), endpoint="local", model="qwen"),
            run_record(tmp_path, "cloud", standard_cases(bug_found=False))]  # fmt: skip

    comparison = build_comparison(runs)

    assert comparison.labels == ("local", "cloud")
    assert cell(comparison.summary, "model", 0) == "qwen"
    assert cell(comparison.summary, "endpoint", 1) == "remote"
    assert cell(comparison.summary, "fixtures scored", 0) == "3 (1 failed)"
    assert cell(comparison.summary, "risk exact", 0) == "67%"
    assert cell(comparison.summary, "issues found", 0) == "2/3 (67%)"
    assert cell(comparison.summary, "issues found", 1) == "1/3 (33%)"
    assert cell(comparison.summary, "controls flagged", 0) == "1/1"
    assert cell(comparison.summary, "tokens in (cost basis)", 0) == "3,000"
    assert cell(comparison.summary, "tokens out", 0) == "300"
    assert cell(comparison.summary, "mean time per fixture", 0) == "2.0s"


def test_recall_is_broken_down_by_context_and_a_missing_tag_is_a_dash(tmp_path: Path):
    comparison = build_comparison([run_record(tmp_path, "run", standard_cases())])

    assert cell(comparison.summary, "recall: in_diff") == "1/1 (100%)"
    assert cell(comparison.summary, "recall: needs_context") == "1/2 (50%)"
    assert cell(comparison.summary, "recall: removed_check") == "-"


def test_an_unknown_cost_is_not_shown_as_free_and_a_price_gives_a_cost(tmp_path: Path):
    unpriced = run_record(tmp_path, "unpriced", standard_cases())
    priced = run_record(tmp_path, "priced", standard_cases(), price_in=1.0, price_out=2.0)
    runs = [unpriced, priced]

    summary = build_comparison(runs).summary

    assert cell(summary, "cost", 0) == "unknown"
    # 3 scored fixtures x (1000 in, 100 out) at $1 and $2 per million tokens
    assert cell(summary, "cost", 1) == "$0.0036"


def test_the_per_fixture_table_shows_risk_found_false_alarms_and_failures(tmp_path: Path):
    comparison = build_comparison([run_record(tmp_path, "run", standard_cases())])

    assert dict(comparison.fixtures) == {
        "bug-a": ("HIGH->HIGH 1/1 fa1",),
        "bug-b": ("CRITICAL->MEDIUM 1/2 fa0",),
        "control": ("LOW->LOW control fa1",),
        "slow-one": ("FAILED",),
    }


def test_a_rate_with_nothing_to_count_is_n_a_not_zero(tmp_path: Path):
    only_failed = [CaseResult("x", error="boom")]

    summary = build_comparison([run_record(tmp_path, "run", only_failed)]).summary

    assert cell(summary, "risk exact") == "n/a"
    assert cell(summary, "precision") == "n/a"
    assert cell(summary, "issues found") == "0/0 (n/a)"
    assert cell(summary, "mean time per fixture") == "n/a"


def test_runs_over_different_fixtures_are_compared_on_the_shared_ones_and_say_so(tmp_path: Path):
    full = run_record(tmp_path, "full", standard_cases())
    partial = run_record(tmp_path, "partial", standard_cases()[:2])

    comparison = build_comparison([full, partial])

    assert [name for name, _ in comparison.fixtures] == ["bug-a", "bug-b"]
    assert any("do not cover the same fixtures" in note and "2 that every run has" in note
               for note in comparison.notes)  # fmt: skip


def test_runs_with_different_line_tolerances_are_flagged(tmp_path: Path):
    runs = [run_record(tmp_path, "strict", standard_cases()),
            run_record(tmp_path, "lenient", standard_cases(), line_tolerance=2)]  # fmt: skip

    notes = build_comparison(runs).notes

    assert any("different line tolerances" in note for note in notes)


def test_runs_over_the_same_fixtures_and_tolerance_need_no_warning(tmp_path: Path):
    runs = [
        run_record(tmp_path, "a", standard_cases()),
        run_record(tmp_path, "b", standard_cases()),
    ]

    assert len(build_comparison(runs).notes) == 2  # the legend and the remote-pricing note


def test_markdown_has_both_tables_with_the_labels_as_columns(tmp_path: Path):
    runs = [
        run_record(tmp_path, "local", standard_cases()),
        run_record(tmp_path, "cloud", standard_cases()),
    ]

    text = to_markdown(build_comparison(runs))

    assert "## Summary" in text and "## Per fixture" in text
    assert "|  | `local` | `cloud` |" in text
    assert "| issues found | 2/3 (67%) | 2/3 (67%) |" in text
    assert "| bug-a | HIGH->HIGH 1/1 fa1 | HIGH->HIGH 1/1 fa1 |" in text
    assert "n/a means nothing was countable." in text


def test_text_that_looks_like_rich_markup_is_shown_literally(tmp_path: Path):
    record = run_record(tmp_path, "run", standard_cases(), model="weird[bold]model")
    buffer = io.StringIO()
    console = Console(file=buffer, width=200, force_terminal=False)

    for table in to_rich(build_comparison([record])):
        console.print(table)

    assert "weird[bold]model" in buffer.getvalue()


def test_the_command_prints_the_tables_and_writes_markdown(tmp_path: Path):
    for label in ("local", "cloud"):
        run_record(tmp_path, label, standard_cases())
    out = tmp_path / "report" / "RESULTS.md"

    result = runner.invoke(
        app,
        [
            "compare",
            str(tmp_path / "local.json"),
            str(tmp_path / "cloud.json"),
            "--markdown",
            str(out),
        ],
    )

    assert result.exit_code == 0
    assert "Summary" in result.output and "Per fixture" in result.output
    assert out.read_text(encoding="utf-8").startswith("## Summary")


def test_the_command_refuses_two_runs_with_the_same_label(tmp_path: Path):
    run_record(tmp_path, "same", standard_cases())
    copy = tmp_path / "copy.json"
    copy.write_text((tmp_path / "same.json").read_text(encoding="utf-8"), encoding="utf-8")

    result = runner.invoke(app, ["compare", str(tmp_path / "same.json"), str(copy)])

    assert result.exit_code == 2
    assert "same label" in result.output


@pytest.mark.parametrize("bad", ["missing.json"])
def test_the_command_reports_an_unreadable_result_file(tmp_path: Path, bad: str):
    result = runner.invoke(app, ["compare", str(tmp_path / bad)])

    assert result.exit_code == 2
    assert bad in result.output


def test_repricing_applies_the_given_prices_to_the_billed_tokens(tmp_path: Path):
    remote = run_record(
        tmp_path, "cloud", standard_cases()
    )  # 3 scored cases: 3,000 billed in, 300 out

    summary = build_comparison([remote], price_in=1.0, price_out=2.0).summary

    assert cell(summary, "cost") == "$0.0036"
    assert any(
        "repriced" in note for note in build_comparison([remote], price_in=1.0, price_out=2.0).notes
    )


def test_without_given_prices_each_run_keeps_its_own_stored_cost(tmp_path: Path):
    stored = run_record(tmp_path, "cloud", standard_cases(), price_in=1.0, price_out=2.0)

    assert cell(build_comparison([stored]).summary, "cost") == "$0.0036"
    assert cell(build_comparison([stored]).summary, "tokens in (cost basis)") == "3,000"
