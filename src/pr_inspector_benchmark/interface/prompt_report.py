"""Prompt sections for the Markdown comparison: one group per candidate prompt.

Runs are grouped by the fingerprint of the system prompt they used. A manifest kept outside the
repository can give each group a title, a change note and a verdict, so candidate prose is written
once and never committed with the code.
"""

import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pr_inspector_benchmark.infrastructure.run_store import RunRecord
from pr_inspector_benchmark.interface.formatting import percent

UNKNOWN = "unknown"
PREVIEW = 160
_FINGERPRINT = re.compile(r"[0-9a-f]{10}")
_KEYS = frozenset({"title", "change", "verdict"})
RUN_HEADER = [
    "Run", "Scored", "Found", "False alarms", "Precision", "Controls flagged",
    "Risk exact", "Risk within one", "Failed", "Output tokens",
]  # fmt: skip


class ManifestError(Exception):
    """Raised when the manifest cannot be read or does not have the expected shape."""


@dataclass(frozen=True)
class PromptNote:
    title: str = ""
    change: str = ""
    verdict: str = ""


def load_manifest(path: Path) -> dict[str, PromptNote]:
    """Read one TOML table per prompt, named by its fingerprint."""
    try:
        prompts = tomllib.loads(path.read_text(encoding="utf-8")).get("prompts", {})
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ManifestError(f"{path}: {exc}") from exc
    if not isinstance(prompts, dict):
        raise ManifestError(f"{path}: [prompts] must be a table")
    for sha, entry in prompts.items():
        if not _FINGERPRINT.fullmatch(sha):
            raise ManifestError(
                f"{path}: {sha!r} is not a prompt fingerprint (10 lowercase hex characters)"
            )
        if (
            not isinstance(entry, dict)
            or not set(entry) <= _KEYS
            or not all(isinstance(value, str) for value in entry.values())
        ):
            raise ManifestError(
                f"{path}: [prompts.{sha}] may only hold string values for {sorted(_KEYS)}"
            )
    return {sha: PromptNote(**entry) for sha, entry in prompts.items()}


def group_runs(runs: Sequence[RunRecord]) -> dict[str, list[RunRecord]]:
    """Runs grouped by prompt fingerprint, in fingerprint order; runs with none go last."""
    groups: dict[str, list[RunRecord]] = {}
    for run in sorted(runs, key=lambda run: run.label):
        groups.setdefault(run.prompt_sha or UNKNOWN, []).append(run)
    return dict(sorted(groups.items(), key=lambda item: (item[0] == UNKNOWN, item[0])))


def _mean(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def _fixed(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _of(part: int, whole: int) -> str:
    return f"{part}/{whole}" if whole else "n/a"


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    def line(cells: Sequence[str]) -> str:
        return "| " + " | ".join(str(cell).replace("|", "\\|") for cell in cells) + " |"

    return "\n".join([line(header), "|" + "---|" * len(header), *map(line, rows)])


def _run_row(run: RunRecord) -> list[str]:
    s, t = run.summary, run.totals
    return [
        run.label,
        str(s.cases),
        f"{s.found_issues}/{s.expected_issues}",
        str(s.false_positives),
        percent(s.precision),
        f"{s.controls_with_reports}/{s.control_cases}",
        _of(s.risk_exact_cases, s.cases),
        _of(s.risk_near_cases, s.cases),
        str(t.failed_cases),
        f"{t.output_tokens:,}",
    ]


def _mean_row(runs: Sequence[RunRecord]) -> list[str]:
    s = [run.summary for run in runs]

    def avg(values: list) -> str:
        return _fixed(_mean(values))

    precision = _mean([x.precision for x in s])
    return [
        "mean",
        avg([x.cases for x in s]),
        f"{avg([x.found_issues for x in s])} of {avg([x.expected_issues for x in s])}",
        avg([x.false_positives for x in s]),
        "n/a" if precision is None else percent(precision),
        f"{avg([x.controls_with_reports for x in s])} of {avg([x.control_cases for x in s])}",
        f"{avg([x.risk_exact_cases for x in s])} of {avg([x.cases for x in s])}",
        f"{avg([x.risk_near_cases for x in s])} of {avg([x.cases for x in s])}",
        f"{sum(run.totals.failed_cases for run in runs)} in total",
        _fixed(_mean([run.totals.output_tokens for run in runs]), digits=0),
    ]


def _group_section(sha: str, runs: Sequence[RunRecord], note: PromptNote) -> str:
    if sha == UNKNOWN:
        parts = [
            "### Runs without a prompt fingerprint",
            "",
            "Saved before prompt fingerprints were recorded, so the prompt they used is not known.",
            "",
        ]
    else:
        parts = [f"### {note.title or 'Unnamed prompt'} (`{sha}`)", ""]
    if note.change:
        parts += [f"**Change.** {note.change}", ""]
    if note.verdict:
        parts += [f"**Verdict.** {note.verdict}", ""]
    rows = [_run_row(run) for run in runs] + [_mean_row(runs)]
    parts += [
        _table(RUN_HEADER, rows),
        "",
        "Means are over the runs in this group. A failed case is left out of its run's rates "
        "and counted in the Failed column.",
        "",
    ]
    return "\n".join(parts)


def _failed_replies(runs: Sequence[RunRecord]) -> str | None:
    rows = []
    for run in sorted(runs, key=lambda run: run.label):
        for case in run.cases:
            if case.error is None:
                continue
            if case.raw_reply is None:
                finish, reply = "-", "not recorded"
            else:
                note = f"[{case.raw_reply.note}] " if case.raw_reply.note else ""
                finish = case.raw_reply.finish_reason or "-"
                reply = " ".join((note + case.raw_reply.content).split())[:PREVIEW] or "(empty)"
            rows.append([run.label, case.id, case.error, finish, reply])
    if not rows:
        return None
    header = ["Run", "Fixture", "Error", "Finish reason", f"Reply (first {PREVIEW} characters)"]
    return "### Failed replies\n\n" + _table(header, rows) + "\n"


def prompt_sections(runs: Sequence[RunRecord], manifest: Mapping[str, PromptNote]) -> str:
    """The Markdown sections that group the runs by the prompt they used."""
    parts = ["## By prompt", ""]
    for sha, members in group_runs(runs).items():
        note = PromptNote() if sha == UNKNOWN else manifest.get(sha, PromptNote())
        parts.append(_group_section(sha, members, note))
    failed = _failed_replies(runs)
    if failed:
        parts.append(failed)
    return "\n".join(parts)
