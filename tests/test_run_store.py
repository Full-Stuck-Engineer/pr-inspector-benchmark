"""Tests for the run settings, their cost rule, and the JSON run store."""

import json
from pathlib import Path

import pytest

from pr_inspector_benchmark.domain.entities import ContextNeeded, RiskLevel
from pr_inspector_benchmark.domain.results import CaseResult, CaseScore, RunResult, Telemetry
from pr_inspector_benchmark.domain.runs import RunInfo
from pr_inspector_benchmark.domain.scoring import summarize
from pr_inspector_benchmark.infrastructure.run_store import RunStoreError, read_run, write_run

ESTIMATES = {"a": 1000, "b": 1000, "c": 1000}


def make_info(**overrides) -> RunInfo:
    fields = {
        "label": "local-qwen",
        "model": "qwen2.5-coder:7b",
        "endpoint": "local",
        "started_at": "2026-11-23T20:00:00+00:00",
    }
    return RunInfo(**{**fields, **overrides})


# --- RunInfo ------------------------------------------------------------------------------


def test_cost_is_unknown_without_prices_never_zero():
    assert make_info().cost_usd(1_000_000, 500_000) is None
    assert make_info(price_in=0.15).cost_usd(1_000_000, 500_000) is None  # output price missing


def test_cost_is_computed_per_million_tokens():
    info = make_info(price_in=0.15, price_out=0.60)

    assert info.cost_usd(1_000_000, 500_000) == pytest.approx(0.45)


def test_a_local_run_with_zero_prices_costs_exactly_zero():
    assert make_info(price_in=0.0, price_out=0.0).cost_usd(12_345, 678) == 0.0


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"label": "../escape"}, "slug"),
        ({"label": "Has Space"}, "slug"),
        ({"model": "  "}, "model"),
        ({"endpoint": "cloud"}, "endpoint"),
        ({"line_tolerance": -1}, "tolerance"),
        ({"price_in": -0.1}, "prices"),
    ],
)
def test_invalid_run_settings_are_rejected(override: dict, message: str):
    with pytest.raises(ValueError, match=message):
        make_info(**override)


# --- the store ----------------------------------------------------------------------------


def scored(
    case_id: str, found: tuple[bool, ...], reported: int, matched: int, **kwargs
) -> CaseResult:
    score = CaseScore(
        case_id=case_id,
        context=kwargs.get("context", ContextNeeded.IN_DIFF),
        expected_risk=kwargs.get("expected", RiskLevel.HIGH),
        predicted_risk=kwargs.get("predicted", RiskLevel.HIGH),
        expected_found=found,
        reported_count=reported,
        matched_reports=matched,
    )
    telemetry = Telemetry("m", input_tokens=1000, output_tokens=100, latency_ms=2500.04)
    return CaseResult(case_id=case_id, score=score, telemetry=telemetry)


def make_result() -> RunResult:
    cases = (
        scored("a", (True,), 2, 1),  # found, one extra report
        scored(
            "b",
            (True, False),
            1,
            1,
            expected=RiskLevel.CRITICAL,
            predicted=RiskLevel.MEDIUM,
            context=ContextNeeded.NEEDS_CONTEXT,
        ),  # fmt: skip
        scored(
            "c", (), 1, 0, expected=RiskLevel.LOW, predicted=RiskLevel.LOW
        ),  # control, false alarm
        CaseResult(case_id="d", error="LLM response was truncated"),
    )
    scores = [case.score for case in cases if case.score is not None]
    return RunResult(cases=cases, summary=summarize(scores))


def test_a_written_run_reads_back_with_the_same_numbers(tmp_path: Path):
    path = tmp_path / "results" / "local-qwen.json"

    write_run(path, make_info(price_in=0.0, price_out=0.0), make_result())
    record = read_run(path)

    assert (record.label, record.model, record.endpoint) == (
        "local-qwen",
        "qwen2.5-coder:7b",
        "local",
    )
    assert record.summary.cases == 3
    assert record.summary.risk_accuracy == pytest.approx(2 / 3)
    assert record.summary.issue_recall == pytest.approx(2 / 3)
    assert record.summary.precision == pytest.approx(2 / 4)
    assert record.summary.false_positives == 2
    assert record.summary.control_false_positive_rate == 1.0
    assert record.summary.recall_by_context["in_diff"].recall == 1.0
    assert record.summary.recall_by_context["needs_context"].recall == 0.5
    assert record.totals.failed_cases == 1
    assert (record.totals.input_tokens, record.totals.output_tokens) == (3000, 300)
    assert record.totals.mean_latency_ms == 2500.0
    assert record.totals.cost_usd == 0.0


def test_a_failed_case_keeps_its_reason_and_has_no_score(tmp_path: Path):
    path = tmp_path / "run.json"

    write_run(path, make_info(), make_result())
    failed = next(case for case in read_run(path).cases if case.id == "d")

    assert failed.error == "LLM response was truncated"
    assert failed.predicted_risk is None
    assert failed.expected_found is None


def test_a_scored_case_keeps_its_per_fixture_detail(tmp_path: Path):
    path = tmp_path / "run.json"

    write_run(path, make_info(), make_result())
    row = next(case for case in read_run(path).cases if case.id == "b")

    assert (row.expected_risk, row.predicted_risk, row.risk_delta) == ("CRITICAL", "MEDIUM", -2)
    assert row.expected_found == [True, False]
    assert (row.reported, row.matched_reports, row.false_positives) == (1, 1, 0)
    assert row.latency_ms == 2500.0


def test_a_missing_price_gives_an_unknown_cost_not_zero(tmp_path: Path):
    path = tmp_path / "run.json"

    write_run(path, make_info(endpoint="remote"), make_result(), ESTIMATES)
    record = read_run(path)

    assert record.totals.cost_usd is None
    assert (record.price_in, record.price_out) == (None, None)


def test_rates_with_nothing_to_count_are_null_not_zero(tmp_path: Path):
    path = tmp_path / "run.json"
    only_controls = RunResult(cases=(), summary=summarize([]))

    write_run(path, make_info(), only_controls)
    record = read_run(path)

    assert record.summary.risk_accuracy is None
    assert record.summary.issue_recall is None
    assert record.totals.mean_latency_ms is None


def test_the_file_holds_only_whitelisted_top_level_keys_and_no_endpoint(tmp_path: Path):
    path = tmp_path / "run.json"

    write_run(path, make_info(endpoint="remote"), make_result(), ESTIMATES)
    document = json.loads(path.read_text(encoding="utf-8"))

    assert set(document) == {
        "schema_version", "label", "model", "endpoint", "started_at", "line_tolerance",
        "price_in", "price_out", "summary", "totals", "cases",
    }  # fmt: skip
    text = path.read_text(encoding="utf-8").lower()
    for forbidden in ("http", "base_url", "api_key", "secret", "token="):
        assert forbidden not in text


def test_an_unknown_field_is_rejected_on_reading(tmp_path: Path):
    path = tmp_path / "run.json"
    write_run(path, make_info(), make_result())
    document = json.loads(path.read_text(encoding="utf-8"))
    document["base_url"] = "https://private.example/v1"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(RunStoreError, match=r"run\.json"):
        read_run(path)


def test_another_schema_version_is_rejected(tmp_path: Path):
    path = tmp_path / "run.json"
    write_run(path, make_info(), make_result())
    document = json.loads(path.read_text(encoding="utf-8"))
    document["schema_version"] = 1
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(RunStoreError, match="schema version 1 is not supported"):
        read_run(path)


def test_a_missing_file_is_a_store_error(tmp_path: Path):
    with pytest.raises(RunStoreError, match="nope.json"):
        read_run(tmp_path / "nope.json")


def test_a_remote_run_is_priced_on_the_estimate_and_keeps_the_reported_count(tmp_path: Path):
    path = tmp_path / "cloud.json"
    estimates = {"a": 500, "b": 500, "c": 500}  # reported is 1,000 each

    billed = write_run(
        path, make_info(endpoint="remote", price_in=1.0, price_out=0.0), make_result(), estimates
    )
    record = read_run(path)

    assert billed == 1500
    assert record.totals.input_tokens == 3000  # what the endpoint reported, kept for reference
    assert (record.totals.input_tokens_estimated, record.totals.input_tokens_billed) == (1500, 1500)
    assert record.totals.cost_usd == pytest.approx(0.0015)


def test_a_remote_run_cannot_be_written_without_estimates(tmp_path: Path):
    with pytest.raises(ValueError, match="estimated input tokens"):
        write_run(tmp_path / "cloud.json", make_info(endpoint="remote"), make_result())


def test_a_local_run_is_priced_on_its_reported_count_even_with_estimates(tmp_path: Path):
    path = tmp_path / "local.json"

    billed = write_run(
        path, make_info(price_in=1.0, price_out=0.0), make_result(), {"a": 1, "b": 1, "c": 1}
    )

    assert billed == 3000
    assert read_run(path).totals.cost_usd == pytest.approx(0.003)


def test_a_missing_estimate_for_a_scored_case_is_refused(tmp_path: Path):
    with pytest.raises(ValueError, match="no input token estimate for: c"):
        write_run(tmp_path / "x.json", make_info(), make_result(), {"a": 1, "b": 1})
