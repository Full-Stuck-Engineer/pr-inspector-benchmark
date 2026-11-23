"""What a reviewer reported, and the scores computed from it.

Scores store raw counts and derive every rate from them. A rate whose denominator is zero is
``None``, never 0: "no expected issues" must not read as "found none of them".
"""

from dataclasses import dataclass

from pr_inspector_benchmark.domain.entities import RISK_ORDER, ContextNeeded, RiskLevel


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


@dataclass(frozen=True)
class ReportedIssue:
    """One finding a reviewer reported, anchored at a new-side line."""

    file_path: str
    line_number: int
    severity: RiskLevel
    title: str


@dataclass(frozen=True)
class ReviewOutcome:
    """What a reviewer returned for one case."""

    risk_level: RiskLevel
    issues: tuple[ReportedIssue, ...] = ()


@dataclass(frozen=True)
class CaseScore:
    """How one outcome compares with what a good review should have found."""

    case_id: str
    context: ContextNeeded
    expected_risk: RiskLevel
    predicted_risk: RiskLevel
    expected_found: tuple[bool, ...]  # one flag per expected issue, in fixture order
    reported_count: int
    matched_reports: int  # reports that match at least one expected issue

    @property
    def risk_delta(self) -> int:
        """Predicted minus expected, in levels: negative means the risk was under-estimated."""
        return RISK_ORDER[self.predicted_risk] - RISK_ORDER[self.expected_risk]

    @property
    def risk_exact(self) -> bool:
        return self.risk_delta == 0

    @property
    def risk_near(self) -> bool:
        """Within one level of the expected risk."""
        return abs(self.risk_delta) <= 1

    @property
    def is_control(self) -> bool:
        return not self.expected_found

    @property
    def found_count(self) -> int:
        return sum(self.expected_found)

    @property
    def recall(self) -> float | None:
        return _ratio(self.found_count, len(self.expected_found))

    @property
    def false_positives(self) -> int:
        """Reports that match no expected issue; on a control, every report."""
        return self.reported_count - self.matched_reports
