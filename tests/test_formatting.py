"""Tests for the plain-text formatting of a run."""

import pytest

from pr_inspector_benchmark.domain.entities import ContextNeeded, RiskLevel
from pr_inspector_benchmark.domain.results import CaseResult, CaseScore, RunResult, Telemetry
from pr_inspector_benchmark.domain.runs import RunInfo
from pr_inspector_benchmark.domain.scoring import summarize
from pr_inspector_benchmark.interface.formatting import (
    case_line,
    duration,
    money,
    percent,
    run_summary,
)


def scored(case_id: str, found: tuple[bool, ...], reported: int, matched: int) -> CaseResult:
    score = CaseScore(
        case_id=case_id,
        context=ContextNeeded.IN_DIFF,
        expected_risk=RiskLevel.HIGH if found else RiskLevel.LOW,
        predicted_risk=RiskLevel.CRITICAL if found else RiskLevel.LOW,
        expected_found=found,
        reported_count=reported,
        matched_reports=matched,
    )
    return CaseResult(case_id, score=score, telemetry=Telemetry("m", 2000, 200, 12_345.0))


def test_a_rate_that_could_not_be_computed_is_not_a_zero_percent():
    assert percent(None) == "n/a"
    assert percent(0.0) == "0%"
    assert percent(2 / 3) == "67%"


def test_an_unknown_cost_is_not_a_free_run():
    assert money(None) == "unknown"
    assert money(0.0) == "$0.0000"
    assert money(0.0024) == "$0.0024"


@pytest.mark.parametrize(
    ("milliseconds", "text"),
    [(900, "0.9s"), (12_345, "12.3s"), (59_000, "59.0s"), (62_000, "1m02s"), (3_725_000, "62m05s")],
)
def test_durations_read_naturally(milliseconds: float, text: str):
    assert duration(milliseconds) == text


def test_a_scored_case_line_shows_risk_found_and_false_alarms():
    line = case_line(3, 17, scored("etherpad-static-path-traversal", (True, False), 2, 1))

    assert line.startswith("[ 3/17] etherpad-static-path-traversal")
    assert "HIGH->CRITICAL" in line
    assert "found 1/2" in line
    assert "false alarms 1" in line
    assert line.endswith("12.3s")


def test_a_control_case_line_says_control_instead_of_a_ratio():
    line = case_line(1, 2, scored("clean", (), 0, 0))

    assert "found control" in line
    assert "false alarms 0" in line


def test_a_failed_case_line_shows_the_reason_and_no_score():
    line = case_line(2, 2, CaseResult("slow-one", error="request timed out"))

    assert "FAILED" in line
    assert "request timed out" in line
    assert "found" not in line


def make_run() -> tuple[RunInfo, RunResult]:
    cases = (scored("a", (True,), 2, 1), scored("b", (), 1, 0), CaseResult("c", error="timeout"))
    scores = [case.score for case in cases if case.score is not None]
    info = RunInfo("cloud", "some-model", "remote", "2026-11-23T20:00:00+00:00")
    return info, RunResult(cases=cases, summary=summarize(scores))


def test_the_summary_reports_counts_rates_tokens_and_where_it_was_saved():
    info, result = make_run()

    text = run_summary(info, result, "results/cloud.json", 4000)

    assert "cloud: 3 fixtures, 2 scored, 1 failed" in text
    assert "issues found 1/1 (100%)" in text
    assert "precision 33%" in text
    assert "false alarms 2" in text
    assert "controls flagged 1/1" in text
    assert "tokens in 4,000, out 400" in text
    assert text.endswith("saved results/cloud.json")


def test_the_summary_says_unknown_when_no_price_was_given():
    info, result = make_run()

    assert "cost unknown" in run_summary(info, result, "x.json", 4000)


def test_the_summary_shows_a_cost_once_prices_are_given():
    info, result = make_run()
    priced = RunInfo(
        info.label, info.model, info.endpoint, info.started_at, price_in=1.0, price_out=2.0
    )

    assert "cost $0.0048" in run_summary(priced, result, "x.json", 4000)
