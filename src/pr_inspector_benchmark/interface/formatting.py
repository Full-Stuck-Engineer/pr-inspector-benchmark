"""Plain-text formatting of a run, shared by the commands.

A value that could not be computed is shown as ``n/a`` or ``unknown``, never as 0.
"""

from pr_inspector_benchmark.domain.results import CaseResult, RunResult
from pr_inspector_benchmark.domain.runs import RunInfo


def percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def money(value: float | None) -> str:
    return "unknown" if value is None else f"${value:.4f}"


def duration(milliseconds: float) -> str:
    seconds = milliseconds / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes}m{rest:02d}s"


def case_line(position: int, total: int, result: CaseResult) -> str:
    """One progress line for a finished fixture."""
    head = f"[{position:>2}/{total}] {result.case_id:<40}"
    if result.score is None or result.telemetry is None:
        return f"{head} FAILED  {result.error}"
    score = result.score
    found = (
        f"{score.found_count}/{len(score.expected_found)}" if score.expected_found else "control"
    )
    risk = f"{score.expected_risk.value}->{score.predicted_risk.value}"
    return (
        f"{head} {risk:<18} found {found:<8} false alarms {score.false_positives}"
        f"  {duration(result.telemetry.latency_ms)}"
    )


def run_summary(info: RunInfo, result: RunResult, saved_to: str, billed_input: int) -> str:
    """The closing lines of a run."""
    s = result.summary
    cost = info.cost_usd(billed_input, result.total_output_tokens)
    lines = [
        f"{info.label}: {len(result.cases)} fixtures, {s.cases} scored,"
        f" {len(result.failed)} failed, {duration(result.total_latency_ms)} of model time",
        f"risk exact {percent(s.risk_accuracy)}, near {percent(s.risk_near_accuracy)}"
        f" | issues found {s.found_issues}/{s.expected_issues} ({percent(s.issue_recall)})"
        f" | precision {percent(s.precision)} | false alarms {s.false_positives}",
        f"controls flagged {s.controls_with_reports}/{s.control_cases}"
        f" | tokens in {billed_input:,}, out {result.total_output_tokens:,}"
        f" | cost {money(cost)}",
        f"saved {saved_to}",
    ]
    return "\n".join(lines)
