"""Tests for the JSON fixture loader and its validation against the diff."""

import json
from pathlib import Path

import pytest

from pr_inspector_benchmark.domain.entities import ContextNeeded, RiskLevel
from pr_inspector_benchmark.domain.exceptions import FixtureLoadError
from pr_inspector_benchmark.domain.protocols import FixtureLoader
from pr_inspector_benchmark.infrastructure.fixture_loader import JsonFixtureLoader

# New-side lines: 10 (context), 11 and 12 (added), 13 (context).
DIFF = """\
diff --git a/app/db.py b/app/db.py
index 1111111..2222222 100644
--- a/app/db.py
+++ b/app/db.py
@@ -10,3 +10,4 @@ def find(user):
     cursor = connect()
-    cursor.execute("SELECT * FROM users WHERE id = %s", (user,))
+    query = "SELECT * FROM users WHERE id = '" + user + "'"
+    cursor.execute(query)
     return cursor.fetchall()
"""


def make_fixture(**overrides) -> dict:
    fixture = {
        "id": "sql-injection-example",
        "description": "Query built from user input",
        "language": "python",
        "context": "in_diff",
        "provenance": {
            "repository": "example/project",
            "license": "Apache-2.0",
            "reference": "0123456789abcdef",
            "url": "https://github.com/example/project/commit/0123456789abcdef",
            "construction": "reverse of fix commit (added lines are pre-fix code)",
            "advisory": "GHSA-xxxx-xxxx-xxxx",
        },
        "expected": {
            "risk_level": "CRITICAL",
            "rationale": "Attacker-controlled input reaches the query.",
            "issues": [
                {
                    "file_path": "app/db.py",
                    "line_start": 11,
                    "line_end": 12,
                    "description": "SQL built by string concatenation",
                }
            ],
        },
        "diff": DIFF,
    }
    return {**fixture, **overrides}


def write(directory: Path, name: str, fixture: dict) -> None:
    (directory / name).write_text(json.dumps(fixture), encoding="utf-8")


def load_error(directory: Path) -> str:
    with pytest.raises(FixtureLoadError) as caught:
        JsonFixtureLoader(directory).load_all()
    return str(caught.value)


def test_valid_fixture_loads_into_domain_entities(tmp_path: Path):
    write(tmp_path, "one.json", make_fixture())

    (case,) = JsonFixtureLoader(tmp_path).load_all()

    assert case.id == "sql-injection-example"
    assert case.context is ContextNeeded.IN_DIFF
    assert case.expected_risk is RiskLevel.CRITICAL
    assert case.provenance.advisory == "GHSA-xxxx-xxxx-xxxx"
    assert (case.expected_issues[0].line_start, case.expected_issues[0].line_end) == (11, 12)


def test_loader_satisfies_the_domain_port(tmp_path: Path):
    assert isinstance(JsonFixtureLoader(tmp_path), FixtureLoader)


def test_fixtures_load_in_file_name_order(tmp_path: Path):
    write(tmp_path, "b.json", make_fixture(id="second"))
    write(tmp_path, "a.json", make_fixture(id="first"))

    assert [case.id for case in JsonFixtureLoader(tmp_path).load_all()] == ["first", "second"]


def test_control_fixture_without_issues_loads(tmp_path: Path):
    expected = {"risk_level": "LOW", "rationale": "A mechanical refactor.", "issues": []}
    write(tmp_path, "control.json", make_fixture(id="refactor-control", expected=expected))

    (case,) = JsonFixtureLoader(tmp_path).load_all()

    assert case.is_control is True


def test_issue_window_may_anchor_on_a_context_line(tmp_path: Path):
    # A deleted safety check leaves only context lines on the new side to point at.
    fixture = make_fixture()
    fixture["expected"]["issues"][0].update(line_start=10, line_end=10)
    write(tmp_path, "one.json", fixture)

    assert len(JsonFixtureLoader(tmp_path).load_all()) == 1


def test_missing_directory_is_an_error(tmp_path: Path):
    assert "fixture directory not found" in load_error(tmp_path / "nope")


def test_malformed_json_names_the_file(tmp_path: Path):
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

    assert load_error(tmp_path).startswith("broken.json:")


def test_unknown_field_is_rejected(tmp_path: Path):
    write(tmp_path, "typo.json", make_fixture(descripton="misspelled"))

    message = load_error(tmp_path)

    assert message.startswith("typo.json:")
    assert "descripton" in message


def test_missing_required_field_is_rejected(tmp_path: Path):
    fixture = make_fixture()
    del fixture["language"]
    write(tmp_path, "missing.json", fixture)

    assert "language" in load_error(tmp_path)


def test_unknown_risk_level_is_rejected(tmp_path: Path):
    fixture = make_fixture()
    fixture["expected"]["risk_level"] = "SEVERE"
    write(tmp_path, "risk.json", fixture)

    assert "risk_level" in load_error(tmp_path)


def test_unknown_context_tag_is_rejected(tmp_path: Path):
    write(tmp_path, "tag.json", make_fixture(context="obvious"))

    assert "context" in load_error(tmp_path)


def test_domain_rule_violation_is_reported_with_the_file_name(tmp_path: Path):
    fixture = make_fixture()
    fixture["expected"]["issues"][0].update(line_start=12, line_end=11)
    write(tmp_path, "window.json", fixture)

    message = load_error(tmp_path)

    assert message.startswith("window.json:")
    assert "line window" in message


def test_expected_file_missing_from_the_diff_is_rejected(tmp_path: Path):
    fixture = make_fixture()
    fixture["expected"]["issues"][0]["file_path"] = "app/other.py"
    write(tmp_path, "file.json", fixture)

    message = load_error(tmp_path)

    assert "app/other.py" in message
    assert "not in the diff" in message


def test_window_outside_the_diff_is_rejected(tmp_path: Path):
    fixture = make_fixture()
    fixture["expected"]["issues"][0].update(line_start=40, line_end=50)
    write(tmp_path, "lines.json", fixture)

    assert "does not overlap any new-side line" in load_error(tmp_path)


def test_diff_with_only_ignored_files_is_rejected(tmp_path: Path):
    lockfile_diff = DIFF.replace("app/db.py", "uv.lock")
    write(tmp_path, "noise.json", make_fixture(diff=lockfile_diff))

    assert "no reviewable source file" in load_error(tmp_path)


def test_duplicate_ids_across_files_are_rejected(tmp_path: Path):
    write(tmp_path, "a.json", make_fixture())
    write(tmp_path, "b.json", make_fixture())

    message = load_error(tmp_path)

    assert "duplicate id" in message
    assert "a.json" in message
