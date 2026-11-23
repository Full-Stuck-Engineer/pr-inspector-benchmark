"""Tests for the benchmark entities and the rules a valid fixture must satisfy."""

from dataclasses import FrozenInstanceError

import pytest

from pr_inspector_benchmark.domain.entities import (
    RISK_ORDER,
    BenchmarkCase,
    ContextNeeded,
    ExpectedIssue,
    Provenance,
    RiskLevel,
)
from pr_inspector_benchmark.domain.exceptions import InvalidFixtureError


def make_provenance(**overrides) -> Provenance:
    fields = {
        "repository": "example/project",
        "license": "Apache-2.0",
        "reference": "0123456789abcdef",
        "url": "https://github.com/example/project/commit/0123456789abcdef",
        "construction": "reverse of fix commit (added lines are pre-fix code)",
    }
    return Provenance(**{**fields, **overrides})


def make_issue(**overrides) -> ExpectedIssue:
    fields = {
        "file_path": "app/db.py",
        "line_start": 11,
        "line_end": 12,
        "description": "SQL built by string concatenation",
    }
    return ExpectedIssue(**{**fields, **overrides})


def make_case(**overrides) -> BenchmarkCase:
    fields = {
        "id": "sql-injection-example",
        "description": "Query built from user input",
        "language": "python",
        "context": ContextNeeded.IN_DIFF,
        "provenance": make_provenance(),
        "diff": "diff --git a/app/db.py b/app/db.py\n",
        "expected_risk": RiskLevel.CRITICAL,
        "rationale": "Attacker-controlled input reaches the query.",
        "expected_issues": (make_issue(),),
    }
    return BenchmarkCase(**{**fields, **overrides})


def test_valid_case_is_built_and_is_not_a_control():
    case = make_case()

    assert case.is_control is False
    assert case.expected_issues[0].line_start == 11


def test_case_without_expected_issues_is_a_control():
    control = make_case(expected_issues=(), expected_risk=RiskLevel.LOW)

    assert control.is_control is True


def test_control_must_expect_low_risk():
    with pytest.raises(InvalidFixtureError, match="must expect LOW"):
        make_case(expected_issues=(), expected_risk=RiskLevel.HIGH)


@pytest.mark.parametrize("bad_id", ["", "Has Space", "UPPER", "-leading", "dot.ted"])
def test_id_must_be_a_lowercase_slug(bad_id: str):
    with pytest.raises(InvalidFixtureError, match="lowercase slug"):
        make_case(id=bad_id)


@pytest.mark.parametrize("field", ["description", "language", "diff", "rationale"])
def test_case_text_fields_must_not_be_blank(field: str):
    with pytest.raises(InvalidFixtureError, match=field):
        make_case(**{field: "   "})


@pytest.mark.parametrize("field", ["repository", "license", "reference", "url", "construction"])
def test_provenance_fields_must_not_be_blank(field: str):
    with pytest.raises(InvalidFixtureError, match=f"provenance {field}"):
        make_provenance(**{field: ""})


@pytest.mark.parametrize("field", ["file_path", "description"])
def test_expected_issue_text_fields_must_not_be_blank(field: str):
    with pytest.raises(InvalidFixtureError, match=field):
        make_issue(**{field: " "})


@pytest.mark.parametrize(("start", "end"), [(0, 5), (-1, 3), (12, 11)])
def test_line_window_must_satisfy_one_le_start_le_end(start: int, end: int):
    with pytest.raises(InvalidFixtureError, match="line window"):
        make_issue(line_start=start, line_end=end)


def test_single_line_window_is_valid():
    assert make_issue(line_start=7, line_end=7).line_end == 7


def test_entities_are_immutable():
    with pytest.raises(FrozenInstanceError):
        make_case().id = "changed"  # type: ignore[misc]


def test_risk_levels_are_ordered_from_low_to_critical():
    ordered = sorted(RiskLevel, key=RISK_ORDER.__getitem__)

    assert ordered == [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
