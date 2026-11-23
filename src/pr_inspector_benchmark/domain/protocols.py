"""Domain ports (Protocols) defining the benchmark's external boundaries."""

from typing import Protocol, runtime_checkable

from pr_inspector_benchmark.domain.entities import BenchmarkCase
from pr_inspector_benchmark.domain.results import ReviewOutcome, Telemetry


@runtime_checkable
class FixtureLoader(Protocol):
    """Port for reading the benchmark cases from wherever they are stored."""

    def load_all(self) -> list[BenchmarkCase]:
        """Load every case, failing on the first invalid one."""
        ...


@runtime_checkable
class ReviewerPort(Protocol):
    """Port for the reviewer under test."""

    def review(self, case: BenchmarkCase) -> tuple[ReviewOutcome, Telemetry]:
        """Review the case's diff.

        Raises ``ReviewFailedError`` when the review cannot be completed.
        """
        ...
