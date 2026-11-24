"""What a reviewer reported, and the scores computed from it.

Scores store raw counts and derive every rate from them. A rate whose denominator is zero is
``None``, never 0: "no expected issues" must not read as "found none of them".
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

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


@dataclass(frozen=True)
class ContextTally:
    """Expected issues found, out of those expected, for one context tag."""

    found: int
    expected: int

    @property
    def recall(self) -> float | None:
        return _ratio(self.found, self.expected)


@dataclass(frozen=True)
class ScoreSummary:
    """Scores pooled over a run. Recall is pooled over issues: "found X of Y"."""

    cases: int
    risk_exact_cases: int
    risk_near_cases: int
    expected_issues: int
    found_issues: int
    reported_issues: int
    matched_reports: int
    control_cases: int
    controls_with_reports: int
    by_context: Mapping[ContextNeeded, ContextTally] = field(default_factory=dict)

    @property
    def risk_accuracy(self) -> float | None:
        return _ratio(self.risk_exact_cases, self.cases)

    @property
    def risk_near_accuracy(self) -> float | None:
        return _ratio(self.risk_near_cases, self.cases)

    @property
    def issue_recall(self) -> float | None:
        return _ratio(self.found_issues, self.expected_issues)

    @property
    def precision(self) -> float | None:
        return _ratio(self.matched_reports, self.reported_issues)

    @property
    def false_positives(self) -> int:
        return self.reported_issues - self.matched_reports

    @property
    def control_false_positive_rate(self) -> float | None:
        """Share of controls where the reviewer reported anything at all."""
        return _ratio(self.controls_with_reports, self.control_cases)


@dataclass(frozen=True)
class Telemetry:
    """Cost and latency of one review."""

    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float


@dataclass(frozen=True)
class RawReply:
    """The model's reply to a review that failed, kept so the failure can be diagnosed.

    ``note`` says why the reply could not be read as a chat completion, when that is the case.
    """

    status: int | None
    finish_reason: str | None
    content: str
    note: str | None = None


@dataclass(frozen=True)
class CaseResult:
    """The result for one case: a score with its telemetry, or the reason the review failed."""

    case_id: str
    score: CaseScore | None = None
    telemetry: Telemetry | None = None
    error: str | None = None
    raw_reply: RawReply | None = None

    def __post_init__(self) -> None:
        scored = self.score is not None and self.telemetry is not None
        failed = self.error is not None and self.score is None and self.telemetry is None
        if scored == failed:  # neither shape, since both at once is impossible
            raise ValueError("a case result holds either a score with telemetry, or an error")
        if self.raw_reply is not None and not failed:
            raise ValueError("only a failed case can hold a raw reply")

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class RunResult:
    """Every case of a run, plus the summary over the cases that could be scored.

    Failed cases are left out of the summary and counted separately, so a rate is never
    silently computed over fewer cases than the run had. The tokens of a failed review are
    unknown, so the token totals cover successful reviews only.
    """

    cases: tuple[CaseResult, ...]
    summary: ScoreSummary

    @property
    def failed(self) -> tuple[CaseResult, ...]:
        return tuple(case for case in self.cases if not case.succeeded)

    def _telemetry(self) -> list[Telemetry]:
        return [case.telemetry for case in self.cases if case.telemetry is not None]

    @property
    def total_input_tokens(self) -> int:
        return sum(t.input_tokens for t in self._telemetry())

    @property
    def total_output_tokens(self) -> int:
        return sum(t.output_tokens for t in self._telemetry())

    @property
    def total_latency_ms(self) -> float:
        return sum(t.latency_ms for t in self._telemetry())

    @property
    def mean_latency_ms(self) -> float | None:
        telemetry = self._telemetry()
        return self.total_latency_ms / len(telemetry) if telemetry else None
