"""Tests for the benchmark runner, using in-memory fakes only."""

import pytest

from pr_inspector_benchmark.application.use_cases.run_benchmark import RunBenchmarkUseCase
from pr_inspector_benchmark.domain.entities import (
    BenchmarkCase,
    ContextNeeded,
    ExpectedIssue,
    Provenance,
    RiskLevel,
)
from pr_inspector_benchmark.domain.exceptions import ReviewFailedError
from pr_inspector_benchmark.domain.protocols import FixtureLoader, ReviewerPort
from pr_inspector_benchmark.domain.results import (
    CaseResult,
    ReportedIssue,
    ReviewOutcome,
    Telemetry,
)

PATH = "app/db.py"


def make_case(case_id: str, start: int = 10, end: int = 12) -> BenchmarkCase:
    return BenchmarkCase(
        id=case_id,
        description="a change",
        language="python",
        context=ContextNeeded.IN_DIFF,
        provenance=Provenance(
            "example/project", "MIT", "abc123", "https://example.test", "reverse"
        ),
        diff="diff --git a/app/db.py b/app/db.py\n",
        expected_risk=RiskLevel.HIGH,
        rationale="why",
        expected_issues=(ExpectedIssue(PATH, start, end, "expected"),),
    )


def hit(line: int = 11) -> ReviewOutcome:
    """An outcome that finds the default expected issue."""
    issue = ReportedIssue(PATH, line, RiskLevel.HIGH, "finding")
    return ReviewOutcome(RiskLevel.HIGH, (issue,))


class FakeLoader:
    def __init__(self, cases: list[BenchmarkCase]) -> None:
        self._cases = cases

    def load_all(self) -> list[BenchmarkCase]:
        return list(self._cases)


class ScriptedReviewer:
    """Answers each case id with a canned outcome, or raises the canned exception."""

    def __init__(self, script: dict[str, ReviewOutcome | Exception]) -> None:
        self._script = script
        self.seen: list[str] = []

    def review(self, case: BenchmarkCase) -> tuple[ReviewOutcome, Telemetry]:
        self.seen.append(case.id)
        answer = self._script[case.id]
        if isinstance(answer, Exception):
            raise answer
        return answer, Telemetry("fake-model", input_tokens=100, output_tokens=10, latency_ms=250.0)


def run(cases: list[BenchmarkCase], script: dict, **options):
    reviewer = ScriptedReviewer(script)
    result = RunBenchmarkUseCase(FakeLoader(cases), reviewer, **options).execute()
    return result, reviewer


def test_fakes_satisfy_the_domain_ports():
    assert isinstance(FakeLoader([]), FixtureLoader)
    assert isinstance(ScriptedReviewer({}), ReviewerPort)


def test_every_case_is_reviewed_once_and_scored_in_fixture_order():
    cases = [make_case("a"), make_case("b"), make_case("c")]

    result, reviewer = run(cases, {"a": hit(), "b": hit(), "c": hit()})

    assert reviewer.seen == ["a", "b", "c"]
    assert [r.case_id for r in result.cases] == ["a", "b", "c"]
    assert all(r.succeeded for r in result.cases)
    assert result.summary.cases == 3
    assert result.summary.issue_recall == 1.0


def test_a_failing_review_is_recorded_and_the_run_continues():
    cases = [make_case("a"), make_case("b"), make_case("c")]
    script = {"a": hit(), "b": ReviewFailedError("LLM response was truncated"), "c": hit()}

    result, reviewer = run(cases, script)

    assert reviewer.seen == ["a", "b", "c"]  # "c" still ran after "b" failed
    assert [r.succeeded for r in result.cases] == [True, False, True]
    assert result.cases[1].error == "LLM response was truncated"
    assert result.cases[1].score is None
    assert [r.case_id for r in result.failed] == ["b"]


def test_failed_cases_are_excluded_from_the_summary_not_scored_as_misses():
    cases = [make_case("a"), make_case("b")]

    result, _ = run(cases, {"a": hit(), "b": ReviewFailedError("timeout")})

    assert result.summary.cases == 1
    assert result.summary.expected_issues == 1
    assert result.summary.issue_recall == 1.0  # not 0.5: the failed case is not a miss


def test_blank_failure_message_still_gives_a_readable_error():
    result, _ = run([make_case("a")], {"a": ReviewFailedError()})

    assert result.cases[0].error == "ReviewFailedError"


def test_an_unexpected_exception_is_a_bug_and_propagates():
    with pytest.raises(RuntimeError, match="boom"):
        run([make_case("a"), make_case("b")], {"a": RuntimeError("boom"), "b": hit()})


def test_line_tolerance_reaches_the_scoring():
    near_miss = ReviewOutcome(RiskLevel.HIGH, (ReportedIssue(PATH, 13, RiskLevel.HIGH, "finding"),))

    strict, _ = run([make_case("a")], {"a": near_miss})
    lenient, _ = run([make_case("a")], {"a": near_miss}, line_tolerance=1)

    assert strict.summary.found_issues == 0
    assert lenient.summary.found_issues == 1


def test_negative_line_tolerance_is_rejected():
    with pytest.raises(ValueError, match="negative"):
        RunBenchmarkUseCase(FakeLoader([]), ScriptedReviewer({}), line_tolerance=-1)


def test_telemetry_is_totalled_over_successful_reviews_only():
    cases = [make_case("a"), make_case("b"), make_case("c")]

    result, _ = run(cases, {"a": hit(), "b": ReviewFailedError("timeout"), "c": hit()})

    assert result.total_input_tokens == 200
    assert result.total_output_tokens == 20
    assert result.total_latency_ms == 500.0
    assert result.mean_latency_ms == 250.0


def test_empty_fixture_set_gives_an_empty_run():
    result, reviewer = run([], {})

    assert result.cases == ()
    assert result.summary.cases == 0
    assert result.mean_latency_ms is None
    assert reviewer.seen == []


def test_case_result_must_hold_a_score_with_telemetry_or_an_error():
    with pytest.raises(ValueError, match="either a score with telemetry, or an error"):
        CaseResult(case_id="a")
    with pytest.raises(ValueError, match="either a score with telemetry, or an error"):
        CaseResult(case_id="a", error="x", telemetry=Telemetry("m", 1, 1, 1.0))


def test_progress_is_reported_after_each_case_in_order():
    seen: list[tuple[int, int, str, bool]] = []
    reviewer = ScriptedReviewer({"a": hit(), "b": ReviewFailedError("timeout"), "c": hit()})
    use_case = RunBenchmarkUseCase(
        FakeLoader([make_case("a"), make_case("b"), make_case("c")]), reviewer
    )

    use_case.execute(on_case=lambda n, total, r: seen.append((n, total, r.case_id, r.succeeded)))

    assert seen == [(1, 3, "a", True), (2, 3, "b", False), (3, 3, "c", True)]
