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
_LINE_COMMENT_MARKERS: dict[str, tuple[str, ...]] = {
    ".py": ("#",),
    ".rb": ("#",),
    ".php": ("//", "#"),
}
_C_STYLE = {
    ".go",
    ".rs",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".kt",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".cs",
}
# Javadoc-style block comment lines: "/*", "*/" or "* text". A bare "*ptr = 0" is code.
_BLOCK_COMMENT_LINE = re.compile(r"/\*|\*/|\*(\s|$)")
_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@")
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


def is_comment_only(line: str, path: str) -> bool:
    """Whether a source line holds nothing but a comment, judged by the file's extension."""
    text = line.strip()
    suffix = PurePosixPath(path).suffix
    if not text:
        return False
    if text.startswith(_LINE_COMMENT_MARKERS.get(suffix, ())) or (
        suffix in _C_STYLE and text.startswith("//")
    ):
        return True
    return suffix in (_C_STYLE | {".php"}) and _BLOCK_COMMENT_LINE.match(text) is not None


def explanatory_lines_to_drop(
    diff: str, *, comments: bool = True, extra: re.Pattern[str] | None = None
) -> dict[str, set[int]]:
    """Old-side line numbers, per file, of deleted lines that only explain the fix.

    In a reversed fix the old side is the fixed code, so its deleted lines show the safeguard
    that the reviewer should notice, but also the comments written to explain it. Comment-only
    lines are listed when ``comments`` is set, and any deleted line matching ``extra``, for
    prose that is not a comment, such as docstring text.
    """
    drops: dict[str, set[int]] = {}
    path: str | None = None
    in_hunk = False
    old_line = 0
    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            path, in_hunk = None, False
        elif not in_hunk and raw.startswith("--- "):
            name = raw[4:].split("\t")[0]
            path = name[2:] if name.startswith("a/") else None
        elif header := _HUNK_HEADER.match(raw):
            in_hunk, old_line = True, int(header.group(1))
        elif in_hunk and path is not None and not raw.startswith("\\"):
            if raw.startswith("-"):
                body = raw[1:]
                if (comments and is_comment_only(body, path)) or (extra and extra.search(body)):
                    drops.setdefault(path, set()).add(old_line)
                old_line += 1
            elif raw.startswith(" "):
                old_line += 1
    return drops


@dataclass(frozen=True)
class ReversedChange:
    """The reversed diff of a commit and the source files it covers."""

    diff: str
    files: tuple[str, ...]
    dropped_lines: int = 0  # explanatory lines removed from the old side


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
    construction = (
        f"reverse of {commit[:10]}: the new side of the diff is the code before the change"
    )
    if change.dropped_lines:
        construction += (
            f"; {change.dropped_lines} explanatory line(s) deleted from the old side were "
            "dropped so the diff does not explain the fix"
        )
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
            "construction": construction,
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
