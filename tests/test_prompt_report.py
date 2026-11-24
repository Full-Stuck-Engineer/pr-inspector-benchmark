"""Tests for the prompt sections of the comparison: grouping, means, manifest, failed replies."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from pr_inspector_benchmark.domain.entities import ContextNeeded, RiskLevel
from pr_inspector_benchmark.domain.results import (
    CaseResult,
    CaseScore,
    RawReply,
    RunResult,
    Telemetry,
)
from pr_inspector_benchmark.domain.runs import RunInfo
from pr_inspector_benchmark.domain.scoring import summarize
from pr_inspector_benchmark.infrastructure.run_store import RunRecord, read_run, write_run
from pr_inspector_benchmark.interface.cli import app
from pr_inspector_benchmark.interface.prompt_report import (
    UNKNOWN,
    ManifestError,
    PromptNote,
    group_runs,
    load_manifest,
    prompt_sections,
)

SHA_A, SHA_B = "aaaaaaaaaa", "bbbbbbbbbb"
runner = CliRunner()


def cases():
    score = CaseScore("bug", ContextNeeded.IN_DIFF, RiskLevel.HIGH, RiskLevel.HIGH, (True,), 1, 1)
    return [
        CaseResult("bug", score=score, telemetry=Telemetry("m", 1000, 100, 2000.0)),
        CaseResult("slow", error="request timed out"),
    ]


def make_run(folder: Path, label: str, prompt_sha=None, failures=()) -> RunRecord:
    """Write a run through the store and read it back, as the comparison will see it."""
    result_cases = cases() + list(failures)
    info = RunInfo(label, "some-model", "local", "2026-11-24T00:00:00+00:00", prompt_sha=prompt_sha)
    summary = summarize([c.score for c in result_cases if c.score is not None])
    path = folder / f"{label}.json"
    write_run(
        path,
        info,
        RunResult(cases=tuple(result_cases), summary=summary),
        {c.case_id: 1000 for c in result_cases},
    )
    return read_run(path)


def test_runs_are_grouped_by_fingerprint_with_unknown_last(tmp_path: Path):
    runs = [
        make_run(tmp_path, "b", SHA_B),
        make_run(tmp_path, "a", SHA_A),
        make_run(tmp_path, "old"),
    ]

    assert list(group_runs(runs)) == [SHA_A, SHA_B, UNKNOWN]


def test_a_manifest_gives_each_prompt_its_title_change_and_verdict(tmp_path: Path):
    path = tmp_path / "manifest.toml"
    path.write_text(
        f'[prompts.{SHA_A}]\ntitle = "Candidate A"\nchange = "shorter"\nverdict = "kept"\n'
    )

    assert load_manifest(path)[SHA_A] == PromptNote("Candidate A", "shorter", "kept")


@pytest.mark.parametrize(
    "text",
    ['[prompts.notahash]\ntitle = "x"\n', f'[prompts.{SHA_A}]\ncolour = "red"\n',
     f"[prompts.{SHA_A}]\ntitle = 3\n", "prompts = 3\n", "[prompts\n"],
)  # fmt: skip
def test_a_bad_manifest_is_refused(tmp_path: Path, text: str):
    path = tmp_path / "manifest.toml"
    path.write_text(text)

    with pytest.raises(ManifestError):
        load_manifest(path)


def test_a_group_shows_its_title_verdict_and_a_mean_row(tmp_path: Path):
    runs = [make_run(tmp_path, "one", SHA_A), make_run(tmp_path, "two", SHA_A)]

    text = prompt_sections(runs, {SHA_A: PromptNote("Candidate A", "shorter", "kept")})

    assert f"### Candidate A (`{SHA_A}`)" in text
    assert "**Verdict.** kept" in text
    assert "| mean |" in text


def test_failed_replies_show_the_reply_or_say_it_was_not_recorded(tmp_path: Path):
    reply = RawReply(status=200, finish_reason="stop", content="line one\nline | two")
    kept = make_run(
        tmp_path,
        "kept",
        SHA_A,
        failures=[CaseResult("refused", error="not valid JSON", raw_reply=reply)],
    )
    old = make_run(tmp_path, "old", SHA_A, failures=[CaseResult("timeout", error="timed out")])

    text = prompt_sections([kept, old], {})

    assert "| kept | refused | not valid JSON | stop | line one line \\| two |" in text
    assert "| old | timeout | timed out | - | not recorded |" in text


def test_the_same_input_gives_the_same_markdown(tmp_path: Path):
    runs = [make_run(tmp_path, "one", SHA_A), make_run(tmp_path, "two", SHA_B)]

    assert prompt_sections(runs, {}) == prompt_sections(runs, {})


def test_runs_saved_before_fingerprints_still_display(tmp_path: Path):
    text = prompt_sections([make_run(tmp_path, "old-run")], {})

    assert "### Runs without a prompt fingerprint" in text
    assert "| old-run |" in text


def test_compare_writes_the_sections_and_refuses_a_manifest_it_cannot_use(tmp_path: Path):
    for label in ("one", "two"):
        make_run(tmp_path, label, SHA_A)
    runs = [str(tmp_path / f"{label}.json") for label in ("one", "two")]
    manifest = tmp_path / "manifest.toml"
    manifest.write_text(f'[prompts.{SHA_A}]\ntitle = "Candidate A"\n')
    out = tmp_path / "report.md"

    ok = runner.invoke(app, ["compare", *runs, "--markdown", str(out), "--manifest", str(manifest)])
    no_markdown = runner.invoke(app, ["compare", *runs, "--manifest", str(manifest)])
    bad = tmp_path / "bad.toml"
    bad.write_text("[prompts.notahash]\n")
    bad_manifest = runner.invoke(
        app, ["compare", *runs, "--markdown", str(out), "--manifest", str(bad)]
    )

    assert ok.exit_code == 0, ok.output
    assert "## By prompt" in out.read_text() and "Candidate A" in out.read_text()
    assert no_markdown.exit_code == 2 and "give --markdown too" in no_markdown.output
    assert bad_manifest.exit_code == 2 and "not a prompt fingerprint" in bad_manifest.output
