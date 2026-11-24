"""The run command: the prompt file it uses, and the withheld model name it can save."""

import hashlib
import json
from pathlib import Path

import pr_inspector.infrastructure.llm.openai_client as client_module
from typer.testing import CliRunner

from pr_inspector_benchmark.domain.entities import RiskLevel
from pr_inspector_benchmark.domain.results import ReviewOutcome, Telemetry
from pr_inspector_benchmark.infrastructure.pr_inspector_reviewer import default_system_prompt
from pr_inspector_benchmark.interface import cli as cli_module

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MODEL = "secret-model-name-7b"
runner = CliRunner()


class RecordingReviewer:
    """Records the system prompt pr-inspector is using at the moment of each review."""

    def __init__(self) -> None:
        self.prompts_seen: list[str] = []

    def review(self, case):
        self.prompts_seen.append(client_module.REVIEW_SYSTEM_PROMPT)
        telemetry = Telemetry(model=MODEL, input_tokens=10, output_tokens=5, latency_ms=1.0)
        return ReviewOutcome(risk_level=RiskLevel.LOW, issues=()), telemetry


def invoke(tmp_path: Path, monkeypatch, *extra: str):
    reviewer = RecordingReviewer()
    monkeypatch.setattr(cli_module, "create_reviewer", lambda settings: reviewer)
    args = [
        "run",
        "--label",
        "candidate-run",
        "--model",
        MODEL,
        "--base-url",
        "http://localhost:11434/v1",
        "--fixtures",
        str(FIXTURES),
        "--only",
        "cobra-stderr-routing",
        "--output-dir",
        str(tmp_path),
        *extra,
    ]
    result = runner.invoke(cli_module.app, args)
    return result, reviewer


def test_a_prompt_file_is_used_for_the_review_and_its_fingerprint_is_saved(
    tmp_path: Path, monkeypatch
):
    prompt = "You are a candidate reviewer.\n"
    prompt_path = tmp_path / "candidate.txt"
    prompt_path.write_text(prompt)

    result, reviewer = invoke(tmp_path, monkeypatch, "--prompt-file", str(prompt_path))

    assert result.exit_code == 0, result.output
    assert reviewer.prompts_seen == [prompt]
    saved = json.loads((tmp_path / "candidate-run.json").read_text())
    assert saved["prompt_sha"] == hashlib.sha256(prompt.encode()).hexdigest()[:10]
    assert saved["schema_version"] == 3


def test_without_a_prompt_file_the_default_prompt_is_used_and_fingerprinted(
    tmp_path: Path, monkeypatch
):
    result, reviewer = invoke(tmp_path, monkeypatch)

    assert result.exit_code == 0, result.output
    assert reviewer.prompts_seen == [default_system_prompt()]
    saved = json.loads((tmp_path / "candidate-run.json").read_text())
    assert saved["prompt_sha"] == hashlib.sha256(default_system_prompt().encode()).hexdigest()[:10]
    assert saved["model"] == MODEL


def test_the_original_prompt_is_back_after_a_run_with_a_prompt_file(tmp_path: Path, monkeypatch):
    original = default_system_prompt()
    prompt_path = tmp_path / "candidate.txt"
    prompt_path.write_text("candidate\n")

    invoke(tmp_path, monkeypatch, "--prompt-file", str(prompt_path))

    assert client_module.REVIEW_SYSTEM_PROMPT == original


def test_withhold_model_keeps_the_model_name_out_of_the_file_and_the_output(
    tmp_path: Path, monkeypatch
):
    result, _ = invoke(tmp_path, monkeypatch, "--withhold-model")

    assert result.exit_code == 0, result.output
    saved_text = (tmp_path / "candidate-run.json").read_text()
    assert MODEL not in saved_text
    assert json.loads(saved_text)["model"] == "withheld"
    assert MODEL not in result.output


def test_an_empty_prompt_file_is_refused(tmp_path: Path, monkeypatch):
    prompt_path = tmp_path / "empty.txt"
    prompt_path.write_text("   \n")

    result, reviewer = invoke(tmp_path, monkeypatch, "--prompt-file", str(prompt_path))

    assert result.exit_code == 2
    assert "is empty" in result.output
    assert reviewer.prompts_seen == []


def test_a_missing_prompt_file_is_refused(tmp_path: Path, monkeypatch):
    result, _ = invoke(tmp_path, monkeypatch, "--prompt-file", str(tmp_path / "nope.txt"))

    assert result.exit_code == 2
    assert "cannot read prompt file" in result.output
