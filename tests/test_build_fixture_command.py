"""Tests for the git change source (against a local repository) and the build-fixture command."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from pr_inspector_benchmark.infrastructure.fixture_builder import FixtureBuildError, ReversedChange
from pr_inspector_benchmark.infrastructure.git_change_source import GitChangeSource
from pr_inspector_benchmark.interface import cli
from pr_inspector_benchmark.interface.cli import app

runner = CliRunner()

BUGGY = 'def find(user):\n    return run("SELECT * FROM users WHERE id = \'" + user + "\'")\n'
FIXED = 'def find(user):\n    return run("SELECT * FROM users WHERE id = %s", (user,))\n'


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )  # fmt: skip
    return done.stdout.strip()


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def remote(tmp_path: Path) -> SimpleNamespace:
    """A local repository with a buggy commit, a fix commit and a docs-only commit."""
    root = tmp_path / "remote"
    repo = root / "owner" / "name"
    (repo / "app").mkdir(parents=True)
    (repo / "tests").mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "uploadpack.allowFilter", "true")
    git(repo, "config", "uploadpack.allowAnySHA1InWant", "true")

    (repo / "app" / "db.py").write_text(BUGGY, encoding="utf-8")
    (repo / "tests" / "test_db.py").write_text("def test_find():\n    pass\n", encoding="utf-8")
    (repo / "README.md").write_text("# project\n", encoding="utf-8")
    buggy = commit_all(repo, "add find")

    (repo / "app" / "db.py").write_text(FIXED, encoding="utf-8")
    (repo / "tests" / "test_db.py").write_text(
        "def test_find():\n    assert True\n", encoding="utf-8"
    )
    (repo / "README.md").write_text("# project\n\nNow safe.\n", encoding="utf-8")
    fix = commit_all(repo, "fix injection")

    (repo / "README.md").write_text("# project\n\nDocs only.\n", encoding="utf-8")
    docs_only = commit_all(repo, "docs")

    template = f"file://{root}/{{repo}}"
    return SimpleNamespace(template=template, buggy=buggy, fix=fix, docs_only=docs_only)


def test_the_diff_is_reversed_so_the_new_side_is_the_buggy_code(remote):
    change = GitChangeSource(remote.template).fetch_reversed_change("owner/name", remote.fix)

    assert change.files == ("app/db.py",)
    added = [
        line[1:] for line in change.diff.splitlines() if line.startswith("+") and line[1] != "+"
    ]
    removed = [
        line[1:] for line in change.diff.splitlines() if line.startswith("-") and line[1] != "-"
    ]
    assert any("'\" + user + \"'" in line for line in added)  # the injectable query is added
    assert any("%s" in line for line in removed)  # the fixed query is what disappears


def test_tests_and_docs_are_left_out_of_the_diff(remote):
    change = GitChangeSource(remote.template).fetch_reversed_change("owner/name", remote.fix)

    assert "test_db" not in change.diff
    assert "README" not in change.diff


def test_an_explicit_base_gives_the_same_change(remote):
    source = GitChangeSource(remote.template)

    default = source.fetch_reversed_change("owner/name", remote.fix)
    explicit = source.fetch_reversed_change("owner/name", remote.fix, base=remote.buggy)

    assert explicit.diff == default.diff


def test_a_change_with_no_reviewable_source_is_refused(remote):
    with pytest.raises(FixtureBuildError, match="no reviewable source file"):
        GitChangeSource(remote.template).fetch_reversed_change("owner/name", remote.docs_only)


def test_an_unknown_commit_is_a_build_error_that_names_the_git_step(remote):
    with pytest.raises(FixtureBuildError, match="git fetch failed"):
        GitChangeSource(remote.template).fetch_reversed_change("owner/name", "a" * 40)


def test_a_malicious_repository_or_revision_never_reaches_git():
    source = GitChangeSource("file:///nonexistent/{repo}")

    with pytest.raises(FixtureBuildError, match="owner/name"):
        source.fetch_reversed_change("--upload-pack=x/y", "a" * 40)
    with pytest.raises(FixtureBuildError, match="hex"):
        source.fetch_reversed_change("owner/name", "--upload-pack=touch /tmp/x")


# --- the command --------------------------------------------------------------------------


class FakeSource:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, str, str | None]] = []

    def fetch_reversed_change(self, repository: str, commit: str, base: str | None = None):
        self.calls.append((repository, commit, base))
        if self.error:
            raise self.error
        return ReversedChange(diff="diff --git a/app/db.py b/app/db.py\n", files=("app/db.py",))


def invoke(monkeypatch, tmp_path: Path, source: FakeSource, *extra: str, fixture_id="sql-bug"):
    monkeypatch.setattr(cli, "create_change_source", lambda: source)
    args = [
        "build-fixture", "--repo", "owner/name", "--commit", "abc1234", "--id", fixture_id,
        "--license", "MIT", "--output-dir", str(tmp_path / "fixtures"), *extra,
    ]  # fmt: skip
    return runner.invoke(app, args)


def test_command_writes_a_skeleton_named_after_the_id(monkeypatch, tmp_path: Path):
    source = FakeSource()

    result = invoke(monkeypatch, tmp_path, source)

    assert result.exit_code == 0
    skeleton = json.loads((tmp_path / "fixtures" / "sql-bug.json").read_text(encoding="utf-8"))
    assert skeleton["id"] == "sql-bug"
    assert skeleton["provenance"]["license"] == "MIT"
    assert source.calls == [("owner/name", "abc1234", None)]
    assert "TODO" in result.output


def test_command_passes_the_pull_request_and_base_through(monkeypatch, tmp_path: Path):
    source = FakeSource()

    invoke(monkeypatch, tmp_path, source, "--pr", "5", "--base", "def5678")

    skeleton = json.loads((tmp_path / "fixtures" / "sql-bug.json").read_text(encoding="utf-8"))
    assert skeleton["provenance"]["url"] == "https://github.com/owner/name/pull/5"
    assert source.calls == [("owner/name", "abc1234", "def5678")]


def test_command_refuses_to_overwrite_unless_forced(monkeypatch, tmp_path: Path):
    invoke(monkeypatch, tmp_path, FakeSource())
    target = tmp_path / "fixtures" / "sql-bug.json"
    target.write_text("hand edited", encoding="utf-8")

    refused = invoke(monkeypatch, tmp_path, FakeSource())
    assert refused.exit_code == 2
    assert "already exists" in refused.output
    assert target.read_text(encoding="utf-8") == "hand edited"

    forced = invoke(monkeypatch, tmp_path, FakeSource(), "--force")
    assert forced.exit_code == 0
    assert json.loads(target.read_text(encoding="utf-8"))["id"] == "sql-bug"


@pytest.mark.parametrize("bad_id", ["../escape", "a/b", "Upper Case"])
def test_an_id_that_could_escape_the_output_directory_is_rejected_before_any_work(
    monkeypatch, tmp_path: Path, bad_id: str
):
    source = FakeSource()

    result = invoke(monkeypatch, tmp_path, source, fixture_id=bad_id)

    assert result.exit_code == 2
    assert "lowercase slug" in result.output
    assert source.calls == []
    assert not (tmp_path / "fixtures").exists()


def test_a_build_error_is_reported_and_nothing_is_written(monkeypatch, tmp_path: Path):
    source = FakeSource(error=FixtureBuildError("the change touches no reviewable source file"))

    result = invoke(monkeypatch, tmp_path, source)

    assert result.exit_code == 2
    assert "no reviewable source file" in result.output
    assert not (tmp_path / "fixtures" / "sql-bug.json").exists()
