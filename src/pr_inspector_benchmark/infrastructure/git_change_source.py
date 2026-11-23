"""Fetches a commit from a git remote and reverses its diff for a fixture."""

import re
import subprocess
import tempfile
from pathlib import Path

from pr_inspector_benchmark.infrastructure.fixture_builder import (
    FixtureBuildError,
    ReversedChange,
    explanatory_lines_to_drop,
    is_reviewable_source,
    validate_repository,
    validate_revision,
)


class GitChangeSource:
    """Fetches a commit into a throw-away shallow, blob-filtered clone and reverses its diff."""

    def __init__(self, remote_template: str = "https://github.com/{repo}.git") -> None:
        self._remote_template = remote_template

    def fetch_reversed_change(
        self,
        repository: str,
        commit: str,
        base: str | None = None,
        *,
        drop_comments: bool = True,
        also_drop: str | None = None,
    ) -> ReversedChange:
        """Reverse a commit's diff, dropping the fix's explanatory lines from the old side.

        ``drop_comments`` removes deleted comment-only lines and ``also_drop`` is a regular
        expression for other deleted prose. Without them the diff is git's own, untouched.
        """
        validate_repository(repository)
        validate_revision(commit)
        if base is not None:
            validate_revision(base)
        base_ref = base or f"{commit}^1"
        extra = _compile(also_drop)

        with tempfile.TemporaryDirectory() as workdir:

            def git(*args: str) -> str:
                done = subprocess.run(
                    ["git", *args], cwd=workdir, capture_output=True, text=True, timeout=300
                )
                if done.returncode != 0:
                    raise FixtureBuildError(f"git {args[0]} failed: {done.stderr.strip()}")
                return done.stdout

            git("init", "-q")
            git("remote", "add", "origin", self._remote_template.format(repo=repository))
            git(
                "fetch",
                "-q",
                "--depth=2",
                "--filter=blob:none",
                "origin",
                commit,
                *([base] if base else []),
            )
            names = git("diff", "--name-only", "-z", base_ref, commit).split("\0")
            files = tuple(name for name in names if name and is_reviewable_source(name))
            if not files:
                raise FixtureBuildError("the change touches no reviewable source file")
            diff = git("diff", "--no-color", "--no-ext-diff", commit, base_ref, "--", *files)

            drops = explanatory_lines_to_drop(diff, comments=drop_comments, extra=extra)
            dropped = sum(len(lines) for lines in drops.values())
            if not dropped:
                return ReversedChange(diff=diff, files=files)
            diff = _rewrite_without(git, Path(workdir) / "rewrite", files, commit, base_ref, drops)
            if not diff.strip():
                raise FixtureBuildError("nothing is left of the change once comments are dropped")
            remaining = tuple(f for f in files if f"diff --git a/{f} b/{f}" in diff)
            return ReversedChange(diff=diff, files=remaining, dropped_lines=dropped)


def _compile(pattern: str | None) -> "re.Pattern[str] | None":
    try:
        return re.compile(pattern) if pattern else None
    except re.error as exc:
        raise FixtureBuildError(f"--also-drop is not a valid regular expression: {exc}") from exc


def _rewrite_without(git, root: Path, files, commit: str, base_ref: str, drops) -> str:
    """Regenerate the diff from the old side minus the dropped lines, so git does the hunk math.

    The new side is written unchanged, so every new-side line number stays exactly as it was.
    """
    for path in files:
        try:
            fixed = git("show", f"{commit}:{path}")
            buggy = git("show", f"{base_ref}:{path}")
        except FixtureBuildError as exc:
            raise FixtureBuildError(f"{exc} (added or deleted files need --keep-comments)") from exc
        old_lines = fixed.splitlines(keepends=True)
        kept = "".join(line for n, line in enumerate(old_lines, 1) if n not in drops.get(path, ()))
        for side, text in (("a", kept), ("b", buggy)):
            target = root / side / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    done = subprocess.run(
        ["git", "diff", "--no-index", "--no-color", "--no-prefix", "--no-ext-diff", "a", "b"],
        cwd=root, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    if done.returncode not in (0, 1):  # 1 only means "the sides differ"
        raise FixtureBuildError(f"git diff failed: {done.stderr.strip()}")
    return done.stdout
