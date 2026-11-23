"""Benchmark entities.

A ``BenchmarkCase`` is a real historical change with a known defect, or with none for a
control, together with the findings a good review is expected to report. Line numbers in
expected issues refer to the new side of the diff, the numbering pr-inspector reports.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from pr_inspector_benchmark.domain.exceptions import InvalidFixtureError

_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]*")


class RiskLevel(StrEnum):
    """Severity scale, ordered from LOW to CRITICAL."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# Ordinal position of each level, used to compare a predicted level with the expected one.
RISK_ORDER: dict[RiskLevel, int] = {
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


class ContextNeeded(StrEnum):
    """How a reviewer could find the defect."""

    IN_DIFF = "in_diff"  # visible in the diff itself
    REMOVED_CHECK = "removed_check"  # the defect is a safety check that the diff deletes
    NEEDS_CONTEXT = "needs_context"  # needs knowledge of code outside the diff


def _require_text(value: str, name: str) -> None:
    if not value.strip():
        raise InvalidFixtureError(f"{name} must not be blank")


@dataclass(frozen=True)
class Provenance:
    """Where a fixture comes from, so it can be traced and attributed."""

    repository: str
    license: str
    reference: str  # fix commit or pull request the fixture was built from
    url: str
    construction: str  # how the diff was derived from the reference
    advisory: str | None = None

    def __post_init__(self) -> None:
        for name in ("repository", "license", "reference", "url", "construction"):
            _require_text(getattr(self, name), f"provenance {name}")


@dataclass(frozen=True)
class ExpectedIssue:
    """A finding a good review should report, as a file and a window of new-side lines."""

    file_path: str
    line_start: int
    line_end: int
    description: str

    def __post_init__(self) -> None:
        _require_text(self.file_path, "expected issue file_path")
        _require_text(self.description, "expected issue description")
        if not 1 <= self.line_start <= self.line_end:
            raise InvalidFixtureError(
                f"expected issue line window {self.line_start}-{self.line_end} is invalid: "
                "it needs 1 <= start <= end"
            )


@dataclass(frozen=True)
class BenchmarkCase:
    """One historical change, with the review outcome that counts as correct."""

    id: str
    description: str
    language: str
    context: ContextNeeded
    provenance: Provenance
    diff: str
    expected_risk: RiskLevel
    rationale: str
    expected_issues: tuple[ExpectedIssue, ...] = ()

    def __post_init__(self) -> None:
        if not _ID_PATTERN.fullmatch(self.id):
            raise InvalidFixtureError(
                f"id {self.id!r} must be a lowercase slug (letters, digits, '-' and '_')"
            )
        for name in ("description", "language", "diff", "rationale"):
            _require_text(getattr(self, name), name)
        if self.is_control and self.expected_risk != RiskLevel.LOW:
            raise InvalidFixtureError(
                f"control case {self.id!r} has no expected issues, so it must expect LOW, "
                f"not {self.expected_risk}"
            )

    @property
    def is_control(self) -> bool:
        """A control has no defect; it exists to measure false positives."""
        return not self.expected_issues
