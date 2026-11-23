"""Tests for the pure parts of the fixture builder, and its fit with the loader."""

import json
import re
from pathlib import Path

import pytest

from pr_inspector_benchmark.domain.exceptions import FixtureLoadError
from pr_inspector_benchmark.infrastructure.fixture_builder import (
    FixtureBuildError,
    ReversedChange,
    explanatory_lines_to_drop,
    guess_language,
    is_comment_only,
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


# --- explanatory comments -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "path"),
    [
        ("    # explains the fix", "app/db.py"),
        ("\t// explains the fix", "cmd/main.go"),
        ("  // explains the fix", "src/index.ts"),
        ("/* start of a block", "lib/Foo.java"),
        ("   * javadoc continuation", "lib/Foo.java"),
        ("   */", "lib/Foo.java"),
        ("*", "web/app.js"),
        ("# also a comment in php", "page.php"),
    ],
)
def test_comment_only_lines_are_recognised_by_language(line: str, path: str):
    assert is_comment_only(line, path) is True


@pytest.mark.parametrize(
    ("line", "path"),
    [
        ("x = 1  # trailing comment", "app/db.py"),  # code with a comment is still code
        ("    return run(query)", "app/db.py"),
        ("*ptr = value;", "src/x.c"),  # a pointer dereference, not a comment
        ("a * b", "lib/Foo.java"),
        ("#include <stdio.h>", "src/x.c"),  # a preprocessor line is code
        ("# not a comment in Go", "cmd/main.go"),
        ("", "app/db.py"),
        ("   ", "app/db.py"),
        ("// looks like one", "app/db.py"),  # `//` is floor division territory, not Python
    ],
)
def test_code_and_ambiguous_lines_are_not_treated_as_comments(line: str, path: str):
    assert is_comment_only(line, path) is False


COMMENTED_DIFF = """\
diff --git a/app/db.py b/app/db.py
index 1111111..2222222 100644
--- a/app/db.py
+++ b/app/db.py
@@ -1,6 +1,4 @@
 def find(user):
-    # Parameterized: never concatenate.
-    # This prevents SQL injection.
-    return run("SELECT ... %s", (user,))
+    return run("SELECT ..." + user)
 x = 1
 y = 2
@@ -20,3 +18,2 @@ def other():
     keep = 1
-    # a later comment
     return keep
"""


def test_deleted_comment_lines_are_listed_by_their_old_side_line_number():
    assert explanatory_lines_to_drop(COMMENTED_DIFF) == {"app/db.py": {2, 3, 21}}


def test_deleted_code_is_never_listed():
    drops = explanatory_lines_to_drop(COMMENTED_DIFF)

    assert 4 not in drops["app/db.py"]  # the deleted safeguard is the regression itself


def test_comments_can_be_left_out_of_the_listing():
    assert explanatory_lines_to_drop(COMMENTED_DIFF, comments=False) == {}


def test_extra_pattern_lists_matching_deleted_lines_only():
    drops = explanatory_lines_to_drop(COMMENTED_DIFF, comments=False, extra=re.compile("SELECT"))

    assert drops == {"app/db.py": {4}}  # the added line that also says SELECT is untouched


def test_a_deleted_line_that_looks_like_a_file_header_is_still_content():
    diff = (
        "diff --git a/app/db.py b/app/db.py\n--- a/app/db.py\n+++ b/app/db.py\n"
        "@@ -1,3 +1,2 @@\n keep\n--- a deleted line that starts with dashes\n # keep too\n"
    )

    assert explanatory_lines_to_drop(diff, extra=re.compile("dashes")) == {"app/db.py": {2}}


def test_skeleton_says_when_explanatory_lines_were_dropped():
    change = ReversedChange(diff=DIFF, files=("app/db.py",), dropped_lines=3)

    construction = make_skeleton(change=change)["provenance"]["construction"]

    assert "3 explanatory line(s)" in construction
    assert "does not explain the fix" in construction


def test_skeleton_stays_quiet_when_nothing_was_dropped():
    assert "explanatory" not in make_skeleton()["provenance"]["construction"]
