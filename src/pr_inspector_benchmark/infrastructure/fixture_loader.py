"""Loads benchmark fixtures from JSON files and validates them against their own diff."""

from collections.abc import Sequence
from pathlib import Path

from pr_inspector.infrastructure.git.diff_extractor import GitCliDiffProvider
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pr_inspector_benchmark.domain.entities import (
    BenchmarkCase,
    ContextNeeded,
    ExpectedIssue,
    Provenance,
    RiskLevel,
)
from pr_inspector_benchmark.domain.exceptions import FixtureLoadError, InvalidFixtureError
from pr_inspector_benchmark.domain.protocols import FixtureLoader


class _Strict(BaseModel):
    """Base for the file schema: unknown fields are errors, so typos do not pass silently."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class _IssueFile(_Strict):
    file_path: str
    line_start: int
    line_end: int
    description: str
    extra_windows: list[tuple[int, int]] = Field(default_factory=list)


class _ProvenanceFile(_Strict):
    repository: str
    license: str
    reference: str
    url: str
    construction: str
    advisory: str | None = None


class _ExpectedFile(_Strict):
    risk_level: RiskLevel
    rationale: str
    issues: list[_IssueFile] = Field(default_factory=list)


class _FixtureFile(_Strict):
    id: str
    description: str
    language: str
    context: ContextNeeded
    provenance: _ProvenanceFile
    expected: _ExpectedFile
    diff: str


# Only parse_unified_diff is used; it runs no git command. The same parser feeds the review
# later, so a fixture is checked against exactly what pr-inspector will see.
_DIFF_PARSER = GitCliDiffProvider()


def _to_issue(issue: _IssueFile) -> ExpectedIssue:
    return ExpectedIssue(
        file_path=issue.file_path,
        line_start=issue.line_start,
        line_end=issue.line_end,
        description=issue.description,
        extra_windows=tuple(issue.extra_windows),
    )


def _to_case(fixture: _FixtureFile) -> BenchmarkCase:
    return BenchmarkCase(
        id=fixture.id,
        description=fixture.description,
        language=fixture.language,
        context=fixture.context,
        provenance=Provenance(**fixture.provenance.model_dump()),
        diff=fixture.diff,
        expected_risk=fixture.expected.risk_level,
        rationale=fixture.expected.rationale,
        expected_issues=tuple(_to_issue(issue) for issue in fixture.expected.issues),
    )


def _new_side_lines(diff: str) -> dict[str, set[int]]:
    """New-side line numbers per file, for added and context lines alike."""
    lines: dict[str, set[int]] = {}
    for file_diff in _DIFF_PARSER.parse_unified_diff(diff):
        numbers = lines.setdefault(file_diff.file_path, set())
        for hunk in file_diff.hunks:
            numbers.update(
                line.new_line_number for line in hunk.lines if line.new_line_number is not None
            )
    return lines


def _check_issue_locations(case: BenchmarkCase) -> None:
    """Every expected issue must point at a file and lines that exist in the diff.

    Context lines count as well as added ones: when the defect is a check that the diff
    deletes, the surrounding lines are the only new-side place to anchor the finding.
    """
    available = _new_side_lines(case.diff)
    if not available:
        raise InvalidFixtureError("the diff has no reviewable source file")
    for issue in case.expected_issues:
        numbers = available.get(issue.file_path)
        if numbers is None:
            raise InvalidFixtureError(
                f"expected issue file {issue.file_path!r} is not in the diff "
                f"(files in the diff: {sorted(available)})"
            )
        for start, end in issue.windows:
            if numbers.isdisjoint(range(start, end + 1)):
                raise InvalidFixtureError(
                    f"expected issue window {start}-{end} in {issue.file_path!r} "
                    "does not overlap any new-side line of the diff"
                )


class JsonFixtureLoader:
    """Reads every ``*.json`` fixture in a directory, in file-name order."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def load_all(self) -> list[BenchmarkCase]:
        if not self._directory.is_dir():
            raise FixtureLoadError(f"fixture directory not found: {self._directory}")

        cases: list[BenchmarkCase] = []
        seen: dict[str, str] = {}
        for path in sorted(self._directory.glob("*.json")):
            case = self._load_one(path)
            if case.id in seen:
                raise FixtureLoadError(
                    f"{path.name}: duplicate id {case.id!r} (already used by {seen[case.id]})"
                )
            seen[case.id] = path.name
            cases.append(case)
        return cases

    @staticmethod
    def _load_one(path: Path) -> BenchmarkCase:
        try:
            case = _to_case(_FixtureFile.model_validate_json(path.read_text(encoding="utf-8")))
            _check_issue_locations(case)
        except (OSError, ValidationError, InvalidFixtureError) as exc:
            raise FixtureLoadError(f"{path.name}: {exc}") from exc
        return case


class SubsetFixtureLoader:
    """Loads only the named fixtures from another loader, to run a few cases quickly."""

    def __init__(self, loader: FixtureLoader, ids: Sequence[str]) -> None:
        self._loader = loader
        self._ids = tuple(ids)

    def load_all(self) -> list[BenchmarkCase]:
        cases = self._loader.load_all()
        known = {case.id for case in cases}
        unknown = [fixture_id for fixture_id in self._ids if fixture_id not in known]
        if unknown:
            raise FixtureLoadError(
                f"unknown fixture id(s): {', '.join(unknown)} "
                f"(available: {', '.join(sorted(known))})"
            )
        return [case for case in cases if case.id in self._ids]
