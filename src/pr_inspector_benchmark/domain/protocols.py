"""Domain ports (Protocols) defining the benchmark's external boundaries."""

from typing import Protocol, runtime_checkable

from pr_inspector_benchmark.domain.entities import BenchmarkCase


@runtime_checkable
class FixtureLoader(Protocol):
    """Port for reading the benchmark cases from wherever they are stored."""

    def load_all(self) -> list[BenchmarkCase]:
        """Load every case, failing on the first invalid one."""
        ...
