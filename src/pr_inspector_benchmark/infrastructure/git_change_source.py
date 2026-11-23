"""Fetches a commit from a git remote and reverses its diff for a fixture."""

import subprocess
import tempfile

from pr_inspector_benchmark.infrastructure.fixture_builder import (
    FixtureBuildError,
    ReversedChange,
    is_reviewable_source,
    validate_repository,
    validate_revision,
)


class GitChangeSource:
    """Fetches a commit into a throw-away shallow, blob-filtered clone and reverses its diff."""

    def __init__(self, remote_template: str = "https://github.com/{repo}.git") -> None:
        self._remote_template = remote_template

    def fetch_reversed_change(
        self, repository: str, commit: str, base: str | None = None
    ) -> ReversedChange:
        validate_repository(repository)
        validate_revision(commit)
        if base is not None:
            validate_revision(base)
        base_ref = base or f"{commit}^1"

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
        return ReversedChange(diff=diff, files=files)
