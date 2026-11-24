"""Saves a benchmark run as JSON and reads it back for comparison.

The file holds the numbers and the settings that matter for reading them, and nothing that
identifies an endpoint: no address, no host and no key.
"""

import json
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from pr_inspector_benchmark.domain.results import CaseResult, RawReply, RunResult
from pr_inspector_benchmark.domain.runs import RunInfo, billed_input_tokens

SCHEMA_VERSION = 3
# Version 2 files predate raw replies and prompt fingerprints, and still read fine.
SUPPORTED_SCHEMA_VERSIONS = (2, 3)


class RunStoreError(Exception):
    """Raised when a run file cannot be read or does not have the expected shape."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContextRecallRecord(_Strict):
    found: int
    expected: int
    recall: float | None


class SummaryRecord(_Strict):
    cases: int
    risk_exact_cases: int
    risk_near_cases: int
    risk_accuracy: float | None
    risk_near_accuracy: float | None
    expected_issues: int
    found_issues: int
    issue_recall: float | None
    reported_issues: int
    matched_reports: int
    precision: float | None
    false_positives: int
    control_cases: int
    controls_with_reports: int
    control_false_positive_rate: float | None
    recall_by_context: dict[str, ContextRecallRecord]


class TotalsRecord(_Strict):
    failed_cases: int
    input_tokens: int
    input_tokens_estimated: int | None
    input_tokens_billed: int
    output_tokens: int
    latency_ms: float
    mean_latency_ms: float | None
    cost_usd: float | None


class RawReplyRecord(_Strict):
    status: int | None
    finish_reason: str | None = None
    content: str = ""
    note: str | None = None


class CaseRecord(_Strict):
    """One fixture: a score with its telemetry, or the reason the review failed."""

    id: str
    error: str | None = None
    raw_reply: RawReplyRecord | None = None
    context: str | None = None
    expected_risk: str | None = None
    predicted_risk: str | None = None
    risk_delta: int | None = None
    expected_found: list[bool] | None = None
    reported: int | None = None
    matched_reports: int | None = None
    false_positives: int | None = None
    input_tokens: int | None = None
    input_tokens_estimated: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None


class RunRecord(_Strict):
    schema_version: int
    label: str
    model: str
    endpoint: str
    started_at: str
    line_tolerance: int
    price_in: float | None
    price_out: float | None
    prompt_sha: str | None = None
    summary: SummaryRecord
    totals: TotalsRecord
    cases: list[CaseRecord]


def _raw_reply_record(reply: RawReply | None) -> dict | None:
    if reply is None:
        return None
    return {
        "status": reply.status,
        "finish_reason": reply.finish_reason,
        "content": reply.content,
        "note": reply.note,
    }


def _case_record(case: CaseResult, estimates: Mapping[str, int] | None) -> dict:
    if case.score is None or case.telemetry is None:
        return {
            "id": case.case_id,
            "error": case.error,
            "raw_reply": _raw_reply_record(case.raw_reply),
        }
    score, telemetry = case.score, case.telemetry
    return {
        "id": case.case_id,
        "context": score.context.value,
        "expected_risk": score.expected_risk.value,
        "predicted_risk": score.predicted_risk.value,
        "risk_delta": score.risk_delta,
        "expected_found": list(score.expected_found),
        "reported": score.reported_count,
        "matched_reports": score.matched_reports,
        "false_positives": score.false_positives,
        "input_tokens": telemetry.input_tokens,
        "input_tokens_estimated": None if estimates is None else estimates[case.case_id],
        "output_tokens": telemetry.output_tokens,
        "latency_ms": round(telemetry.latency_ms, 1),
    }


def write_run(
    path: Path, info: RunInfo, result: RunResult, estimates: Mapping[str, int] | None = None
) -> int:
    """Write one run and return the input tokens it is priced on.

    ``estimates`` maps each fixture id to its estimated input tokens. A remote run is priced on
    them, so it cannot be written without them.
    """
    successful = [case for case in result.cases if case.telemetry is not None]
    estimated_total: int | None = None
    if estimates is not None:
        missing = [case.case_id for case in successful if case.case_id not in estimates]
        if missing:
            raise ValueError(f"no input token estimate for: {', '.join(missing)}")
        estimated_total = sum(estimates[case.case_id] for case in successful)
    billed = billed_input_tokens(info.endpoint, result.total_input_tokens, estimated_total)
    cost = info.cost_usd(billed, result.total_output_tokens)
    summary = result.summary
    mean_latency = result.mean_latency_ms
    document = {
        "schema_version": SCHEMA_VERSION,
        "label": info.label,
        "model": info.model,
        "endpoint": info.endpoint,
        "started_at": info.started_at,
        "line_tolerance": info.line_tolerance,
        "price_in": info.price_in,
        "price_out": info.price_out,
        "prompt_sha": info.prompt_sha,
        "summary": {
            "cases": summary.cases,
            "risk_exact_cases": summary.risk_exact_cases,
            "risk_near_cases": summary.risk_near_cases,
            "risk_accuracy": summary.risk_accuracy,
            "risk_near_accuracy": summary.risk_near_accuracy,
            "expected_issues": summary.expected_issues,
            "found_issues": summary.found_issues,
            "issue_recall": summary.issue_recall,
            "reported_issues": summary.reported_issues,
            "matched_reports": summary.matched_reports,
            "precision": summary.precision,
            "false_positives": summary.false_positives,
            "control_cases": summary.control_cases,
            "controls_with_reports": summary.controls_with_reports,
            "control_false_positive_rate": summary.control_false_positive_rate,
            "recall_by_context": {
                context.value: {"found": t.found, "expected": t.expected, "recall": t.recall}
                for context, t in summary.by_context.items()
            },
        },
        "totals": {
            "failed_cases": len(result.failed),
            "input_tokens": result.total_input_tokens,
            "input_tokens_estimated": estimated_total,
            "input_tokens_billed": billed,
            "output_tokens": result.total_output_tokens,
            "latency_ms": round(result.total_latency_ms, 1),
            "mean_latency_ms": None if mean_latency is None else round(mean_latency, 1),
            "cost_usd": None if cost is None else round(cost, 6),
        },
        "cases": [_case_record(case, estimates) for case in result.cases],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return billed


def read_run(path: Path) -> RunRecord:
    """Read and validate a run file."""
    try:
        record = RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise RunStoreError(f"{path.name}: {exc}") from exc
    if record.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise RunStoreError(
            f"{path.name}: schema version {record.schema_version} is not supported "
            f"(expected one of {SUPPORTED_SCHEMA_VERSIONS})"
        )
    return record
