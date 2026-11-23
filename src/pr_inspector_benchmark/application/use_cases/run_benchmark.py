"""Run every fixture through a reviewer and score the outcomes."""

from collections.abc import Callable

from pr_inspector_benchmark.domain.entities import BenchmarkCase
from pr_inspector_benchmark.domain.exceptions import ReviewFailedError
from pr_inspector_benchmark.domain.protocols import FixtureLoader, ReviewerPort
from pr_inspector_benchmark.domain.results import CaseResult, RunResult
from pr_inspector_benchmark.domain.scoring import score_case, summarize


class RunBenchmarkUseCase:
    """Loads the cases, reviews each one and pools the scores.

    A review that fails in a way the reviewer knows about (``ReviewFailedError``) is recorded
    as an error for that case and the run goes on. Any other exception is a bug and
    propagates, so it can never be mistaken for a wrong answer.
    """

    def __init__(
        self,
        loader: FixtureLoader,
        reviewer: ReviewerPort,
        line_tolerance: int = 0,
    ) -> None:
        if line_tolerance < 0:
            raise ValueError("line_tolerance must not be negative")
        self._loader = loader
        self._reviewer = reviewer
        self._line_tolerance = line_tolerance

    def execute(self, on_case: Callable[[int, int, CaseResult], None] | None = None) -> RunResult:
        """Review every case in fixture order.

        ``on_case(position, total, result)`` is called after each case, so a long run can
        report its progress while it goes on.
        """
        cases = self._loader.load_all()
        results = []
        for position, case in enumerate(cases, start=1):
            result = self._run_case(case)
            results.append(result)
            if on_case is not None:
                on_case(position, len(cases), result)
        results = tuple(results)
        scores = [result.score for result in results if result.score is not None]
        return RunResult(cases=results, summary=summarize(scores))

    def _run_case(self, case: BenchmarkCase) -> CaseResult:
        try:
            outcome, telemetry = self._reviewer.review(case)
        except ReviewFailedError as exc:
            return CaseResult(case_id=case.id, error=str(exc) or type(exc).__name__)
        score = score_case(case, outcome, self._line_tolerance)
        return CaseResult(case_id=case.id, score=score, telemetry=telemetry)
