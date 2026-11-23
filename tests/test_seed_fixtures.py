"""Checks on the committed fixture data, so a bad fixture fails in CI rather than in a run."""

from pathlib import Path

import pytest

from pr_inspector_benchmark.domain.entities import BenchmarkCase
from pr_inspector_benchmark.infrastructure.fixture_builder import is_comment_only
from pr_inspector_benchmark.infrastructure.fixture_loader import JsonFixtureLoader

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PERMISSIVE = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC"}


@pytest.fixture(scope="module")
def cases() -> list[BenchmarkCase]:
    return JsonFixtureLoader(FIXTURES).load_all()


def test_every_fixture_loads_and_there_are_some(cases):
    assert cases


def test_file_names_match_fixture_ids(cases):
    assert {path.stem for path in FIXTURES.glob("*.json")} == {case.id for case in cases}


def test_every_fixture_comes_from_a_permissively_licensed_repository(cases):
    assert {case.provenance.license for case in cases} <= PERMISSIVE


def test_every_fixture_is_attributed(cases):
    attribution = (FIXTURES / "ATTRIBUTION.md").read_text(encoding="utf-8")

    for case in cases:
        assert f"`{case.id}`" in attribution, f"{case.id} is not listed in ATTRIBUTION.md"
        assert case.provenance.repository in attribution


def test_no_reversed_fixture_shows_the_fixs_own_comments_as_deleted_lines(cases):
    """A deleted comment would explain the fix to the reviewer and give the answer away.

    This only applies to reversed fixes. A fix taken forward as a control deletes the old
    code's comments naturally.
    """
    for case in cases:
        if not case.provenance.construction.startswith("reverse of"):
            continue
        path = None
        for line in case.diff.splitlines():
            if line.startswith("+++ "):
                path = line[6:]
            elif line.startswith("-") and not line.startswith("---") and path:
                assert not is_comment_only(line[1:], path), f"{case.id}: {line.strip()[:70]}"


def test_a_fixture_that_drops_lines_says_so_in_its_provenance(cases):
    for case in cases:
        if "explanatory line(s)" in case.provenance.construction:
            assert "does not explain the fix" in case.provenance.construction
