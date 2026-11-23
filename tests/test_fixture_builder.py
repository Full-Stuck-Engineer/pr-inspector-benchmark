"""Tests for the pure parts of the fixture builder, and its fit with the loader."""

import json
from pathlib import Path

import pytest

from pr_inspector_benchmark.domain.exceptions import FixtureLoadError
from pr_inspector_benchmark.infrastructure.fixture_builder import (
    FixtureBuildError,
    ReversedChange,
    guess_language,
    is_reviewable_source,
    render_skeleton,
    validate_repository,
    validate_revision,
)
from pr_inspector_benchmark.infrastructure.fixture_loader import JsonFixtureLoader

COMMIT = "0123456789abcdef0123456789abcdef01234567"

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


def make_skeleton(**overrides) -> dict:
    options = {
        "fixture_id": "sql-injection-example",
        "repository": "example/project",
        "license_id": "Apache-2.0",
        "commit": COMMIT,
        "change": ReversedChange(diff=DIFF, files=("app/db.py",)),
    }
    return json.loads(render_skeleton(**{**options, **overrides}))


@pytest.mark.parametrize(
    "path",
    ["app/db.py", "cmd/main.go", "src/index.ts", "lib/Foo.java", "src/lib.rs", "web/App.tsx"],
)
def test_source_files_belong_in_a_fixture(path: str):
    assert is_reviewable_source(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_db.py",  # test directory
        "src/db_test.go",  # Go test file
        "web/app.test.ts",
        "web/app.spec.js",
        "test_helpers.py",
        "docs/guide.md",  # not source
        "README.md",
        "package.json",
        "go.sum",
        "examples/demo.py",  # example directory
        "vendor/lib/x.go",
        "web/node_modules/x/index.js",
        "types/index.d.ts",
        "static/app.min.js",
    ],
)
def test_tests_docs_vendored_and_generated_files_are_left_out(path: str):
    assert is_reviewable_source(path) is False


def test_language_is_the_majority_among_the_files():
    assert guess_language(["a.go", "b.py", "c.go"]) == "go"
    assert guess_language(["web/a.tsx", "web/b.ts", "x.py"]) == "typescript"


def test_a_tie_goes_to_the_first_file():
    assert guess_language(["a.py", "b.go"]) == "python"


@pytest.mark.parametrize("repository", ["spf13/cobra", "ether/etherpad", "a-b/c_d.e"])
def test_valid_repository_names_pass(repository: str):
    validate_repository(repository)


@pytest.mark.parametrize(
    "repository", ["", "owner", "owner/name/extra", "own er/name", "--upload-pack=x/y", "a/b;ls"]
)
def test_invalid_repository_names_are_rejected(repository: str):
    with pytest.raises(FixtureBuildError, match="owner/name"):
        validate_repository(repository)


@pytest.mark.parametrize("revision", ["abc1234", COMMIT])
def test_valid_revisions_pass(revision: str):
    validate_revision(revision)


@pytest.mark.parametrize(
    "revision",
    ["", "abc", "HEAD", "main", "ABCDEF1", "--upload-pack=x", "abc1234; ls", COMMIT + "0"],
)
def test_anything_that_is_not_a_hex_commit_is_rejected(revision: str):
    with pytest.raises(FixtureBuildError, match="hex"):
        validate_revision(revision)


def test_skeleton_for_a_commit_records_provenance_and_the_guessed_language():
    skeleton = make_skeleton(advisory="GHSA-xxxx-xxxx-xxxx")

    assert skeleton["id"] == "sql-injection-example"
    assert skeleton["language"] == "python"
    assert skeleton["diff"] == DIFF
    assert skeleton["provenance"] == {
        "repository": "example/project",
        "license": "Apache-2.0",
        "reference": COMMIT,
        "url": f"https://github.com/example/project/commit/{COMMIT}",
        "construction": "reverse of 0123456789: the new side of the diff is the code before the "
        "change",
        "advisory": "GHSA-xxxx-xxxx-xxxx",
    }


def test_skeleton_for_a_pull_request_points_at_the_pull_request():
    provenance = make_skeleton(pull_request=894)["provenance"]

    assert provenance["reference"] == f"PR #894 (merge commit {COMMIT})"
    assert provenance["url"] == "https://github.com/example/project/pull/894"


def test_skeleton_leaves_everything_only_a_human_knows_as_todo():
    skeleton = make_skeleton()

    todo = [
        skeleton["description"],
        skeleton["context"],
        skeleton["expected"]["risk_level"],
        skeleton["expected"]["rationale"],
        skeleton["expected"]["issues"][0]["description"],
    ]
    assert all(text.startswith("TODO:") for text in todo)
    assert skeleton["expected"]["issues"][0]["file_path"] == "app/db.py"


def test_an_untouched_skeleton_is_rejected_by_the_loader(tmp_path: Path):
    (tmp_path / "sql.json").write_text(json.dumps(make_skeleton()), encoding="utf-8")

    with pytest.raises(FixtureLoadError, match=r"sql\.json"):
        JsonFixtureLoader(tmp_path).load_all()


def test_a_skeleton_the_loader_rejects_is_accepted_once_a_human_fills_it_in(tmp_path: Path):
    skeleton = make_skeleton()
    skeleton.update(description="Query built from user input", context="in_diff")
    skeleton["expected"].update(risk_level="CRITICAL", rationale="Input reaches the query.")
    skeleton["expected"]["issues"][0].update(
        line_start=11, line_end=12, description="SQL built by string concatenation"
    )
    (tmp_path / "sql.json").write_text(json.dumps(skeleton), encoding="utf-8")

    (case,) = JsonFixtureLoader(tmp_path).load_all()

    assert case.id == "sql-injection-example"
    assert case.expected_issues[0].line_start == 11


def test_a_half_filled_skeleton_is_still_rejected(tmp_path: Path):
    skeleton = make_skeleton()
    skeleton.update(description="Query built from user input", context="in_diff")
    skeleton["expected"].update(risk_level="CRITICAL")  # rationale and issue are still TODO
    (tmp_path / "sql.json").write_text(json.dumps(skeleton), encoding="utf-8")

    with pytest.raises(FixtureLoadError, match="TODO"):
        JsonFixtureLoader(tmp_path).load_all()
