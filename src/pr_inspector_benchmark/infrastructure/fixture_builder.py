"""Builds a fixture skeleton from a fix commit.

The fixture's diff is the **reversed** fix: its new side is the code before the fix, so the
review sees the bug as added lines. The expected findings are left as TODO placeholders that
the domain rejects, because only a human can say what a good review should report.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath

SOURCE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".go": "go",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".java": "java",
    ".kt": "kotlin",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cs": "csharp",
}
_NOT_REVIEWED_DIRECTORIES = {
    "test", "tests", "__tests__", "spec", "testdata", "fixtures",
    "docs", "doc", "examples", "example", "vendor", "node_modules", "dist", "build",
}  # fmt: skip
_TEST_FILE = re.compile(r"(_test\.|\.test\.|\.spec\.|(^|/)test_|\.d\.ts$|\.min\.)")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_REVISION = re.compile(r"[0-9a-f]{7,40}")


class FixtureBuildError(Exception):
    """Raised when a fixture cannot be built from the requested change."""


def is_reviewable_source(path: str) -> bool:
    """Whether a changed file belongs in a fixture: source code that is not a test or docs."""
    pure = PurePosixPath(path)
    if pure.suffix not in SOURCE_EXTENSIONS or _TEST_FILE.search(path):
        return False
    return not _NOT_REVIEWED_DIRECTORIES.intersection(pure.parts[:-1])


def guess_language(paths: list[str]) -> str:
    """The language of most of the files; the first one breaks a tie."""
    languages = [SOURCE_EXTENSIONS[PurePosixPath(p).suffix] for p in paths]
    counts = Counter(languages)
    return max(languages, key=lambda language: counts[language])


def validate_repository(repository: str) -> None:
    if not _REPOSITORY.fullmatch(repository) or repository.startswith("-"):
        raise FixtureBuildError(f"repository must look like 'owner/name': {repository!r}")


def validate_revision(revision: str) -> None:
    """A hexadecimal commit id only, so a value can never be read by git as an option."""
    if not _REVISION.fullmatch(revision):
        raise FixtureBuildError(f"commit must be 7 to 40 lowercase hex characters: {revision!r}")


@dataclass(frozen=True)
class ReversedChange:
    """The reversed diff of a commit and the source files it covers."""

    diff: str
    files: tuple[str, ...]


def render_skeleton(
    *,
    fixture_id: str,
    repository: str,
    license_id: str,
    commit: str,
    change: ReversedChange,
    pull_request: int | None = None,
    advisory: str | None = None,
) -> str:
    """The fixture file as JSON text, with TODO placeholders for everything only a human knows."""
    if pull_request is None:
        reference, url = commit, f"https://github.com/{repository}/commit/{commit}"
    else:
        reference = f"PR #{pull_request} (merge commit {commit})"
        url = f"https://github.com/{repository}/pull/{pull_request}"
    skeleton = {
        "id": fixture_id,
        "description": "TODO: describe the change in one sentence",
        "language": guess_language(list(change.files)),
        "context": "TODO: in_diff | removed_check | needs_context",
        "provenance": {
            "repository": repository,
            "license": license_id,
            "reference": reference,
            "url": url,
            "construction": f"reverse of {commit[:10]}: the new side of the diff is the code "
            "before the change",
            "advisory": advisory,
        },
        "expected": {
            "risk_level": "TODO: LOW | MEDIUM | HIGH | CRITICAL",
            "rationale": "TODO: why this risk level",
            "issues": [
                {
                    "file_path": change.files[0],
                    "line_start": 1,
                    "line_end": 1,
                    "description": "TODO: what a good review should report (delete for a control)",
                }
            ],
        },
        "diff": change.diff,
    }
    return json.dumps(skeleton, indent=2, ensure_ascii=False) + "\n"
