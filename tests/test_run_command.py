"""Tests for `pr-bench run`, using fixture files on disk and a fake reviewer (no network)."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pr_inspector_benchmark.domain.entities import BenchmarkCase
from pr_inspector_benchmark.domain.exceptions import ReviewFailedError
from pr_inspector_benchmark.domain.results import ReportedIssue, ReviewOutcome, Telemetry
from pr_inspector_benchmark.infrastructure.run_store import read_run
from pr_inspector_benchmark.infrastructure.token_estimate import estimate_input_tokens
from pr_inspector_benchmark.interface import cli
from pr_inspector_benchmark.interface.cli import app

runner = CliRunner()

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
LOCAL = "http://localhost:11434/v1"
REMOTE = "https://llm.private.example/v1"
SECRET = "sk-test-secret-value-1234"


def write_fixture(directory: Path, fixture_id: str, *, control: bool = False) -> None:
    issues = [] if control else [
        {"file_path": "app/db.py", "line_start": 11, "line_end": 12, "description": "SQL concat"}
    ]  # fmt: skip
    fixture = {
        "id": fixture_id,
        "description": "A change",
        "language": "python",
        "context": "in_diff",
        "provenance": {
            "repository": "example/project", "license": "MIT", "reference": "abc1234",
            "url": "https://github.com/example/project/commit/abc1234", "construction": "reverse",
        },
        "expected": {
            "risk_level": "LOW" if control else "HIGH",
            "rationale": "why",
            "issues": issues,
        },
        "diff": DIFF,
    }  # fmt: skip
    (directory / f"{fixture_id}.json").write_text(json.dumps(fixture), encoding="utf-8")


class FakeReviewer:
    """Finds the first expected issue of each bug and reports nothing on a control."""

    def __init__(self, fail: tuple[str, ...] = ()) -> None:
        self.fail = fail
        self.reviewed: list[str] = []

    def review(self, case: BenchmarkCase) -> tuple[ReviewOutcome, Telemetry]:
        self.reviewed.append(case.id)
        if case.id in self.fail:
            raise ReviewFailedError("request timed out")
        issues = tuple(
            ReportedIssue(i.file_path, i.line_start, case.expected_risk, "finding")
            for i in case.expected_issues[:1]
        )
        return ReviewOutcome(case.expected_risk, issues), Telemetry("m", 1000, 100, 1500.0)


@pytest.fixture
def setup(tmp_path: Path, monkeypatch):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    write_fixture(fixtures, "a-bug")
    write_fixture(fixtures, "b-control", control=True)
    state = {"reviewer": FakeReviewer(), "settings": None}

    def factory(settings):
        state["settings"] = settings
        return state["reviewer"]

    monkeypatch.setattr(cli, "create_reviewer", factory)

    def invoke(*args: str, env: dict | None = None):
        base = ["run", "--fixtures", str(fixtures), "--output-dir", str(tmp_path / "results")]
        return runner.invoke(app, [*base, *args], env=env)

    return invoke, state, tmp_path / "results"


def test_a_local_run_reviews_every_fixture_and_saves_the_run(setup):
    invoke, state, results = setup

    result = invoke("--label", "local-qwen", "--model", "qwen", "--base-url", LOCAL)

    assert result.exit_code == 0
    assert state["reviewer"].reviewed == ["a-bug", "b-control"]
    assert "[ 1/2] a-bug" in result.output and "[ 2/2] b-control" in result.output
    assert "local-qwen: 2 fixtures, 2 scored, 0 failed" in result.output
    record = read_run(results / "local-qwen.json")
    assert (record.endpoint, record.summary.cases) == ("local", 2)
    assert record.totals.cost_usd == 0.0  # a local model costs nothing


def test_a_local_endpoint_needs_no_key_and_gets_a_placeholder(setup):
    invoke, state, _ = setup

    invoke("--label", "local-qwen", "--model", "qwen", "--base-url", LOCAL)

    assert state["settings"].api_key == "ollama"
    assert state["settings"].base_url == LOCAL


def test_a_remote_endpoint_without_a_key_variable_is_refused_before_anything_runs(setup):
    invoke, state, results = setup

    result = invoke("--label", "cloud", "--model", "m", "--base-url", REMOTE)

    assert result.exit_code == 2
    assert "--api-key-env" in result.output
    assert state["settings"] is None
    assert not results.exists()


def test_a_named_key_variable_that_is_not_set_is_an_error_that_names_it(setup):
    invoke, state, results = setup

    result = invoke(
        "--label", "cloud", "--model", "m", "--base-url", REMOTE, "--api-key-env", "NOPE_KEY"
    )

    assert result.exit_code == 2
    assert "NOPE_KEY" in result.output
    assert state["settings"] is None


def test_the_key_comes_from_the_variable_and_never_reaches_the_output_or_the_file(setup):
    invoke, state, results = setup

    result = invoke(
        "--label", "cloud", "--model", "m", "--base-url", REMOTE, "--api-key-env", "MY_KEY",
        env={"MY_KEY": SECRET},
    )  # fmt: skip

    assert result.exit_code == 0
    assert state["settings"].api_key == SECRET
    saved = (results / "cloud.json").read_text(encoding="utf-8")
    for text in (result.output, saved):
        assert SECRET not in text
        assert "private.example" not in text  # nor the address of the endpoint


def test_a_remote_run_without_prices_has_an_unknown_cost(setup):
    invoke, _, results = setup

    invoke(
        "--label",
        "cloud",
        "--model",
        "m",
        "--base-url",
        REMOTE,
        "--api-key-env",
        "K",
        env={"K": "x"},
    )

    assert read_run(results / "cloud.json").totals.cost_usd is None


def test_prices_turn_tokens_into_a_cost(setup):
    invoke, _, results = setup

    invoke(
        "--label", "cloud", "--model", "m", "--base-url", REMOTE, "--api-key-env", "K",
        "--price-in", "1", "--price-out", "2", env={"K": "x"},
    )  # fmt: skip

    # 2 fixtures, priced on their estimated input and 200 output tokens, at $1 and $2 per million
    assert read_run(results / "cloud.json").totals.cost_usd == pytest.approx(
        (2 * estimate_input_tokens(DIFF) + 200 * 2) / 1_000_000
    )


def test_only_runs_the_named_fixtures(setup):
    invoke, state, results = setup

    result = invoke("--label", "quick", "--model", "m", "--base-url", LOCAL, "--only", "b-control")

    assert result.exit_code == 0
    assert state["reviewer"].reviewed == ["b-control"]
    assert read_run(results / "quick.json").summary.cases == 1


def test_an_unknown_only_id_is_an_error_before_any_review(setup):
    invoke, state, results = setup

    result = invoke("--label", "quick", "--model", "m", "--base-url", LOCAL, "--only", "nope")

    assert result.exit_code == 2
    assert "nope" in result.output and "a-bug" in result.output
    assert state["reviewer"].reviewed == []
    assert not (results / "quick.json").exists()


def test_a_failed_review_is_shown_and_saved_and_the_run_goes_on(setup):
    invoke, state, results = setup
    state["reviewer"] = FakeReviewer(fail=("a-bug",))

    result = invoke("--label", "local-qwen", "--model", "qwen", "--base-url", LOCAL)

    assert result.exit_code == 0
    assert "FAILED  request timed out" in result.output
    assert "2 fixtures, 1 scored, 1 failed" in result.output
    assert read_run(results / "local-qwen.json").totals.failed_cases == 1


def test_an_existing_results_file_is_not_overwritten_without_force(setup):
    invoke, state, results = setup
    args = ("--label", "local-qwen", "--model", "qwen", "--base-url", LOCAL)
    invoke(*args)

    refused = invoke(*args)
    forced = invoke(*args, "--force")

    assert refused.exit_code == 2 and "already exists" in refused.output
    assert forced.exit_code == 0


def test_a_label_that_could_escape_the_output_directory_is_rejected(setup):
    invoke, state, results = setup

    result = invoke("--label", "../escape", "--model", "m", "--base-url", LOCAL)

    assert result.exit_code == 2
    assert "slug" in result.output
    assert state["settings"] is None
    assert not results.exists()


def test_a_remote_run_saves_both_the_reported_and_the_estimated_counts(setup):
    invoke, _, results = setup

    invoke(
        "--label",
        "cloud",
        "--model",
        "m",
        "--base-url",
        REMOTE,
        "--api-key-env",
        "K",
        env={"K": "x"},
    )
    record = read_run(results / "cloud.json")

    assert record.totals.input_tokens == 2000  # the fake reviewer reports 1,000 per fixture
    assert record.totals.input_tokens_estimated == 2 * estimate_input_tokens(DIFF)
    assert record.totals.input_tokens_billed == record.totals.input_tokens_estimated


def test_the_compare_command_refuses_a_single_price(setup):
    invoke, _, results = setup
    invoke("--label", "local-qwen", "--model", "qwen", "--base-url", LOCAL)

    from typer.testing import CliRunner

    from pr_inspector_benchmark.interface.cli import app as cli_app

    result = CliRunner().invoke(
        cli_app, ["compare", str(results / "local-qwen.json"), "--price-in", "1"]
    )

    assert result.exit_code == 2
    assert "both --price-in and --price-out" in result.output
