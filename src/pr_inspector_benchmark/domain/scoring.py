"""Scoring rules: how a review outcome is judged against a benchmark case."""

from collections.abc import Sequence

from pr_inspector_benchmark.domain.entities import BenchmarkCase, ContextNeeded, ExpectedIssue
from pr_inspector_benchmark.domain.results import (
    CaseScore,
    ContextTally,
    ReportedIssue,
    ReviewOutcome,
    ScoreSummary,
)


def _normalize(path: str) -> str:
    path = path.strip().replace("\\", "/")
    return path[2:] if path.startswith("./") else path


def _matches(expected: ExpectedIssue, reported: ReportedIssue, tolerance: int) -> bool:
    """Same file, and the reported line inside the expected window widened by ``tolerance``."""
    return (
        _normalize(reported.file_path) == _normalize(expected.file_path)
        and expected.line_start - tolerance <= reported.line_number <= expected.line_end + tolerance
    )


def score_case(case: BenchmarkCase, outcome: ReviewOutcome, line_tolerance: int = 0) -> CaseScore:
    """Judge one outcome against one case.

    An expected issue is found when at least one report matches it, so repeating the same
    finding does not raise recall. A report is a false positive when it matches no expected
    issue, which on a control means every report.
    """
    if line_tolerance < 0:
        raise ValueError("line_tolerance must not be negative")

    reports = outcome.issues
    matches = [[_matches(e, r, line_tolerance) for r in reports] for e in case.expected_issues]
    return CaseScore(
        case_id=case.id,
        context=case.context,
        expected_risk=case.expected_risk,
        predicted_risk=outcome.risk_level,
        expected_found=tuple(any(row) for row in matches),
        reported_count=len(reports),
        matched_reports=sum(any(row[j] for row in matches) for j in range(len(reports))),
    )


def summarize(scores: Sequence[CaseScore]) -> ScoreSummary:
    """Pool case scores into the numbers a run is reported by."""
    tallies: dict[ContextNeeded, tuple[int, int]] = {}
    for score in scores:
        if score.is_control:
            continue
        found, expected = tallies.get(score.context, (0, 0))
        tallies[score.context] = (found + score.found_count, expected + len(score.expected_found))

    controls = [score for score in scores if score.is_control]
    return ScoreSummary(
        cases=len(scores),
        risk_exact_cases=sum(score.risk_exact for score in scores),
        risk_near_cases=sum(score.risk_near for score in scores),
        expected_issues=sum(len(score.expected_found) for score in scores),
        found_issues=sum(score.found_count for score in scores),
        reported_issues=sum(score.reported_count for score in scores),
        matched_reports=sum(score.matched_reports for score in scores),
        control_cases=len(controls),
        controls_with_reports=sum(score.reported_count > 0 for score in controls),
        by_context={ctx: ContextTally(found, exp) for ctx, (found, exp) in tallies.items()},
    )
