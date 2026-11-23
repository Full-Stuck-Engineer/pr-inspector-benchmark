"""Tests for the scoring rules and the run summary."""

import pytest

from pr_inspector_benchmark.domain.entities import (
    BenchmarkCase,
    ContextNeeded,
    ExpectedIssue,
    Provenance,
    RiskLevel,
)
from pr_inspector_benchmark.domain.results import ReportedIssue, ReviewOutcome
from pr_inspector_benchmark.domain.scoring import score_case, summarize

PATH = "app/db.py"
LOW, MEDIUM, HIGH, CRITICAL = (
    RiskLevel.LOW,
    RiskLevel.MEDIUM,
    RiskLevel.HIGH,
    RiskLevel.CRITICAL,
)


def make_case(
    *windows: tuple[int, int],
    risk: RiskLevel = HIGH,
    context: ContextNeeded = ContextNeeded.IN_DIFF,
    case_id: str = "case",
) -> BenchmarkCase:
    """A case with one expected issue per (start, end) window; no windows makes a control."""
    issues = tuple(ExpectedIssue(PATH, start, end, "expected") for start, end in windows)
    return BenchmarkCase(
        id=case_id,
        description="a change",
        language="python",
        context=context,
        provenance=Provenance(
            "example/project", "MIT", "abc123", "https://example.test", "reverse"
        ),
        diff="diff --git a/app/db.py b/app/db.py\n",
        expected_risk=risk if issues else LOW,
        rationale="why",
        expected_issues=issues,
    )


def reported(line: int, path: str = PATH, severity: RiskLevel = HIGH) -> ReportedIssue:
    return ReportedIssue(file_path=path, line_number=line, severity=severity, title="finding")


def outcome(*issues: ReportedIssue, risk: RiskLevel = HIGH) -> ReviewOutcome:
    return ReviewOutcome(risk_level=risk, issues=issues)


# --- risk ---------------------------------------------------------------------------------


def test_exact_risk_is_exact_and_near():
    score = score_case(make_case((10, 12), risk=HIGH), outcome(risk=HIGH))

    assert (score.risk_exact, score.risk_near, score.risk_delta) == (True, True, 0)


@pytest.mark.parametrize(
    ("expected", "predicted", "delta"),
    [(HIGH, CRITICAL, 1), (HIGH, MEDIUM, -1), (LOW, MEDIUM, 1), (CRITICAL, HIGH, -1)],
)
def test_one_level_off_is_near_but_not_exact(expected, predicted, delta):
    score = score_case(make_case((10, 12), risk=expected), outcome(risk=predicted))

    assert (score.risk_exact, score.risk_near, score.risk_delta) == (False, True, delta)


@pytest.mark.parametrize(
    ("expected", "predicted", "delta"), [(CRITICAL, MEDIUM, -2), (LOW, CRITICAL, 3)]
)
def test_two_or_more_levels_off_is_neither_exact_nor_near(expected, predicted, delta):
    score = score_case(make_case((10, 12), risk=expected), outcome(risk=predicted))

    assert (score.risk_exact, score.risk_near, score.risk_delta) == (False, False, delta)


# --- matching -----------------------------------------------------------------------------


def test_report_inside_the_window_finds_the_expected_issue():
    score = score_case(make_case((10, 12)), outcome(reported(11)))

    assert score.expected_found == (True,)
    assert score.recall == 1.0
    assert score.false_positives == 0


@pytest.mark.parametrize("line", [10, 12])
def test_window_edges_are_inclusive(line: int):
    assert score_case(make_case((10, 12)), outcome(reported(line))).expected_found == (True,)


@pytest.mark.parametrize("line", [9, 13])
def test_line_just_outside_the_window_misses_without_tolerance(line: int):
    score = score_case(make_case((10, 12)), outcome(reported(line)))

    assert score.expected_found == (False,)
    assert score.false_positives == 1


@pytest.mark.parametrize(("line", "found"), [(8, False), (9, True), (13, True), (14, False)])
def test_tolerance_widens_the_window_on_both_sides(line: int, found: bool):
    score = score_case(make_case((10, 12)), outcome(reported(line)), line_tolerance=1)

    assert score.expected_found == (found,)


def test_same_line_in_a_different_file_does_not_match():
    score = score_case(make_case((10, 12)), outcome(reported(11, path="app/other.py")))

    assert score.expected_found == (False,)
    assert score.false_positives == 1


def test_leading_dot_slash_in_a_reported_path_is_ignored():
    score = score_case(make_case((10, 12)), outcome(reported(11, path="./app/db.py")))

    assert score.expected_found == (True,)


def test_negative_tolerance_is_rejected():
    with pytest.raises(ValueError, match="negative"):
        score_case(make_case((10, 12)), outcome(), line_tolerance=-1)


# --- recall and false positives -----------------------------------------------------------


def test_duplicate_reports_for_one_expected_issue_do_not_raise_recall_or_count_as_false():
    score = score_case(make_case((10, 12)), outcome(reported(10), reported(11), reported(12)))

    assert score.recall == 1.0
    assert score.matched_reports == 3
    assert score.false_positives == 0


def test_one_report_can_find_two_overlapping_expected_issues():
    score = score_case(make_case((10, 14), (12, 20)), outcome(reported(13)))

    assert score.expected_found == (True, True)
    assert (score.reported_count, score.matched_reports) == (1, 1)


def test_partial_recall_and_a_false_positive_are_counted_separately():
    score = score_case(make_case((10, 12), (30, 32)), outcome(reported(11), reported(99)))

    assert score.expected_found == (True, False)
    assert score.recall == 0.5
    assert score.false_positives == 1


def test_expected_issues_but_no_reports_gives_zero_recall():
    score = score_case(make_case((10, 12)), outcome())

    assert score.recall == 0.0
    assert score.false_positives == 0


def test_control_without_reports_has_no_recall_and_no_false_positives():
    score = score_case(make_case(), outcome(risk=LOW))

    assert score.is_control is True
    assert score.recall is None
    assert score.false_positives == 0


def test_every_report_on_a_control_is_a_false_positive():
    score = score_case(make_case(), outcome(reported(5), reported(6), risk=MEDIUM))

    assert score.false_positives == 2
    assert score.risk_near is True


# --- summary ------------------------------------------------------------------------------


def test_empty_run_has_counts_of_zero_and_no_rates():
    summary = summarize([])

    assert summary.cases == 0
    assert summary.risk_accuracy is None
    assert summary.risk_near_accuracy is None
    assert summary.issue_recall is None
    assert summary.precision is None
    assert summary.control_false_positive_rate is None
    assert summary.by_context == {}


def test_summary_pools_four_cases():
    scores = [
        # exact risk, 1 of 1 found, one extra report
        score_case(make_case((10, 12), case_id="a"), outcome(reported(11), reported(99))),
        # two levels under-estimated, 1 of 2 found
        score_case(
            make_case((5, 5), (20, 25), risk=CRITICAL, context=ContextNeeded.NEEDS_CONTEXT),
            outcome(reported(5), risk=MEDIUM),
        ),
        # control that drew a false report
        score_case(make_case(case_id="c"), outcome(reported(3), risk=LOW)),
        # clean control
        score_case(make_case(case_id="d"), outcome(risk=LOW)),
    ]

    summary = summarize(scores)

    assert summary.cases == 4
    assert (summary.risk_exact_cases, summary.risk_near_cases) == (3, 3)
    assert summary.risk_accuracy == 0.75
    assert summary.risk_near_accuracy == 0.75
    assert (summary.expected_issues, summary.found_issues) == (3, 2)
    assert summary.issue_recall == pytest.approx(2 / 3)
    assert (summary.reported_issues, summary.matched_reports) == (4, 2)
    assert summary.precision == 0.5
    assert summary.false_positives == 2
    assert (summary.control_cases, summary.controls_with_reports) == (2, 1)
    assert summary.control_false_positive_rate == 0.5


def test_summary_breaks_recall_down_by_context_and_leaves_controls_out():
    scores = [
        score_case(make_case((10, 12)), outcome(reported(11))),
        score_case(
            make_case((5, 5), (20, 25), context=ContextNeeded.NEEDS_CONTEXT),
            outcome(reported(5)),
        ),
        score_case(make_case(context=ContextNeeded.REMOVED_CHECK), outcome(risk=LOW)),
    ]

    by_context = summarize(scores).by_context

    assert set(by_context) == {ContextNeeded.IN_DIFF, ContextNeeded.NEEDS_CONTEXT}
    assert by_context[ContextNeeded.IN_DIFF].recall == 1.0
    assert by_context[ContextNeeded.NEEDS_CONTEXT].recall == 0.5
    assert (
        by_context[ContextNeeded.NEEDS_CONTEXT].found,
        by_context[ContextNeeded.NEEDS_CONTEXT].expected,
    ) == (1, 2)
