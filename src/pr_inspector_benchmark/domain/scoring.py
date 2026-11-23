"""Scoring rules: how a review outcome is judged against a benchmark case."""

from pr_inspector_benchmark.domain.entities import BenchmarkCase, ExpectedIssue
from pr_inspector_benchmark.domain.results import CaseScore, ReportedIssue, ReviewOutcome


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
