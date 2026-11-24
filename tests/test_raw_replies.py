"""Tests for keeping the raw reply of a failed case: from the reply hook to the run file."""

import json
from pathlib import Path

import pytest
from pr_inspector.domain.entities import PRReviewResult
from pr_inspector.domain.exceptions import ReviewExecutionError
from pydantic import ValidationError

from pr_inspector_benchmark.domain.entities import (
    BenchmarkCase,
    ContextNeeded,
    ExpectedIssue,
    Provenance,
    RiskLevel,
)
from pr_inspector_benchmark.domain.exceptions import ReviewFailedError
from pr_inspector_benchmark.domain.results import (
    CaseResult,
    CaseScore,
    RawReply,
    RunResult,
    Telemetry,
)
from pr_inspector_benchmark.domain.runs import RunInfo
from pr_inspector_benchmark.domain.scoring import summarize
from pr_inspector_benchmark.infrastructure.pr_inspector_reviewer import (
    REPLY_CHARACTER_LIMIT,
    PrInspectorReviewer,
    _capture,
    _record_reply,
)
from pr_inspector_benchmark.infrastructure.run_store import read_run, write_run

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


def make_case() -> BenchmarkCase:
    return BenchmarkCase(
        id="sql-injection-example",
        description="Query built from user input",
        language="python",
        context=ContextNeeded.IN_DIFF,
        provenance=Provenance(
            "example/project", "MIT", "abc123", "https://example.test", "reverse"
        ),
        diff=DIFF,
        expected_risk=RiskLevel.CRITICAL,
        rationale="Attacker-controlled input reaches the query.",
        expected_issues=(ExpectedIssue("app/db.py", 11, 12, "SQL built by concatenation"),),
    )


class FakeResponse:
    """Stands in for the httpx response the SDK hands to the hook."""

    def __init__(self, status: int, body: str) -> None:
        self.status_code = status
        self.content = body.encode()
        self.text = body

    def read(self) -> bytes:
        return self.content


def chat_body(content: str, finish_reason: str = "stop") -> str:
    return json.dumps(
        {"choices": [{"finish_reason": finish_reason, "message": {"content": content}}]}
    )


# --- the domain -------------------------------------------------------------------------


def test_only_a_failed_case_can_hold_a_raw_reply():
    reply = RawReply(status=200, finish_reason="stop", content="{}")
    score = CaseScore(
        case_id="a",
        context=ContextNeeded.IN_DIFF,
        expected_risk=RiskLevel.LOW,
        predicted_risk=RiskLevel.LOW,
        expected_found=(),
        reported_count=0,
        matched_reports=0,
    )

    assert CaseResult(case_id="a", error="bad reply", raw_reply=reply).raw_reply == reply
    with pytest.raises(ValueError, match="only a failed case"):
        CaseResult(
            case_id="a",
            score=score,
            telemetry=Telemetry(model="m", input_tokens=1, output_tokens=1, latency_ms=1.0),
            raw_reply=reply,
        )


# --- the reply hook ---------------------------------------------------------------------


def test_the_hook_keeps_the_status_finish_reason_and_content_of_a_chat_reply():
    _record_reply(FakeResponse(200, chat_body("the reply", finish_reason="length")))

    assert _capture.reply == {
        "status": 200,
        "finish_reason": "length",
        "content": "the reply",
    }


def test_the_hook_keeps_a_body_that_is_not_a_chat_reply_with_a_note():
    _record_reply(FakeResponse(502, "<html>bad gateway</html>"))

    assert _capture.reply["status"] == 502
    assert _capture.reply["note"] == "reply was not in chat-completion format"
    assert _capture.reply["content"] == "<html>bad gateway</html>"


def test_a_long_reply_is_cut_to_the_limit():
    _record_reply(FakeResponse(200, chat_body("x" * (REPLY_CHARACTER_LIMIT + 500))))

    assert len(_capture.reply["content"]) == REPLY_CHARACTER_LIMIT


# --- the adapter ------------------------------------------------------------------------


class FailingAfterReply:
    """A reviewer whose HTTP reply arrives and is then refused by pr-inspector."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def review(self, diffs):
        _record_reply(
            FakeResponse(200, chat_body("partial SECRET-123 reply", finish_reason="length"))
        )
        raise self._error


def test_a_failed_review_carries_its_redacted_reply():
    inner = FailingAfterReply(ReviewExecutionError("provider echoed SECRET-123"))
    reviewer = PrInspectorReviewer(inner, secrets=("SECRET-123",))

    with pytest.raises(ReviewFailedError) as caught:
        reviewer.review(make_case())

    assert "SECRET-123" not in str(caught.value)
    assert caught.value.raw_reply == RawReply(
        status=200, finish_reason="length", content="partial *** reply"
    )


def test_an_invalid_json_reply_carries_its_redacted_reply_and_a_generic_message():
    try:
        PRReviewResult.model_validate_json("not json")
    except ValidationError as exc:
        validation_error = exc
    inner = FailingAfterReply(validation_error)
    reviewer = PrInspectorReviewer(inner, secrets=("SECRET-123",))

    with pytest.raises(ReviewFailedError) as caught:
        reviewer.review(make_case())

    assert str(caught.value) == "the model's reply was not valid review JSON"
    assert caught.value.raw_reply.content == "partial *** reply"


def test_the_sdk_hook_is_pinned_to_the_client_the_adapter_uses():
    # The capture hooks the SDK's private httpx client. If the SDK renames it, this fails
    # here, instead of silently recording no replies.
    from pr_inspector_benchmark.infrastructure.pr_inspector_reviewer import (
        ReviewerSettings,
        build_reviewer,
    )

    reviewer = build_reviewer(
        ReviewerSettings(model="m", base_url="http://localhost:11434/v1", api_key="k")
    )

    assert _record_reply in reviewer._reviewer.client._client.event_hooks["response"]


# --- the run file -----------------------------------------------------------------------


def failed_result() -> RunResult:
    return RunResult(
        cases=(
            CaseResult(
                case_id="refused",
                error="the model's reply was not valid review JSON",
                raw_reply=RawReply(status=200, finish_reason="stop", content='{"summary":'),
            ),
            CaseResult(case_id="no-reply", error="timed out"),
        ),
        summary=summarize([]),
    )


def test_a_run_file_keeps_the_raw_reply_of_a_failed_case_only(tmp_path: Path):
    info = RunInfo(
        label="candidate-run",
        model="withheld",
        endpoint="local",
        started_at="2026-11-24T00:00:00+00:00",
        prompt_sha="0123456789",
    )
    path = tmp_path / "candidate-run.json"

    write_run(path, info, failed_result())
    record = read_run(path)

    assert record.prompt_sha == "0123456789"
    refused, no_reply = record.cases
    assert refused.raw_reply is not None
    assert refused.raw_reply.content == '{"summary":'
    assert refused.raw_reply.finish_reason == "stop"
    assert no_reply.raw_reply is None
