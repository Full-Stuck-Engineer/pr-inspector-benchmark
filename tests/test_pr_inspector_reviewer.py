"""Tests for the pr-inspector adapter, using a fake pr-inspector reviewer (no network)."""

import pytest
from pr_inspector.domain.entities import FileDiff, TelemetryRecord
from pr_inspector.domain.entities import PRReviewResult as PrResult
from pr_inspector.domain.entities import ReviewIssue as PrIssue
from pr_inspector.domain.entities import RiskLevel as PrRisk
from pr_inspector.domain.exceptions import ReviewExecutionError
from pydantic import ValidationError

from pr_inspector_benchmark.domain.entities import (
    BenchmarkCase,
    ContextNeeded,
    ExpectedIssue,
    Provenance,
    RiskLevel,
)
from pr_inspector_benchmark.domain.exceptions import ConfigurationError, ReviewFailedError
from pr_inspector_benchmark.domain.protocols import ReviewerPort
from pr_inspector_benchmark.infrastructure.pr_inspector_reviewer import (
    DEFAULT_TIMEOUT_SECONDS,
    PrInspectorReviewer,
    ReviewerSettings,
    build_reviewer,
    is_local_endpoint,
)

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


class FakeInner:
    """Stands in for pr-inspector's reviewer: records what it is given, answers or raises."""

    def __init__(self, answer: PrResult | Exception) -> None:
        self._answer = answer
        self.received: list[FileDiff] = []

    def review(self, diffs: list[FileDiff]) -> tuple[PrResult, TelemetryRecord]:
        self.received = diffs
        if isinstance(self._answer, Exception):
            raise self._answer
        telemetry = TelemetryRecord("qwen2.5-coder:7b", 1200, 90, 4200.5, "2026-11-23T00:00:00Z")
        return self._answer, telemetry


def pr_result() -> PrResult:
    issue = PrIssue(
        file_path="app/db.py",
        line_number=11,
        severity=PrRisk.CRITICAL,
        title="SQL injection",
        description="Concatenated query",
    )
    return PrResult(summary="One problem", risk_level=PrRisk.CRITICAL, issues=[issue])


def test_adapter_satisfies_the_reviewer_port():
    assert isinstance(PrInspectorReviewer(FakeInner(pr_result())), ReviewerPort)


def test_result_and_telemetry_are_mapped_into_benchmark_types():
    outcome, telemetry = PrInspectorReviewer(FakeInner(pr_result())).review(make_case())

    assert outcome.risk_level is RiskLevel.CRITICAL
    (issue,) = outcome.issues
    assert (issue.file_path, issue.line_number, issue.title) == ("app/db.py", 11, "SQL injection")
    assert issue.severity is RiskLevel.CRITICAL
    assert (telemetry.model, telemetry.input_tokens, telemetry.output_tokens) == (
        "qwen2.5-coder:7b",
        1200,
        90,
    )
    assert telemetry.latency_ms == 4200.5


def test_the_case_diff_is_parsed_with_pr_inspectors_parser_before_review():
    inner = FakeInner(pr_result())

    PrInspectorReviewer(inner).review(make_case())

    assert [d.file_path for d in inner.received] == ["app/db.py"]
    assert inner.received[0].hunks[0].new_start == 10


def test_a_known_pr_inspector_failure_becomes_a_review_failed_error():
    reviewer = PrInspectorReviewer(FakeInner(ReviewExecutionError("response was truncated")))

    with pytest.raises(ReviewFailedError, match="response was truncated"):
        reviewer.review(make_case())


def test_an_unexpected_exception_is_not_swallowed():
    reviewer = PrInspectorReviewer(FakeInner(RuntimeError("bug")))

    with pytest.raises(RuntimeError, match="bug"):
        reviewer.review(make_case())


def test_an_api_key_echoed_by_the_provider_is_redacted_everywhere():
    error = ReviewExecutionError("401: Incorrect API key provided: sk-secret-123")
    reviewer = PrInspectorReviewer(FakeInner(error), secrets=("sk-secret-123",))

    with pytest.raises(ReviewFailedError) as caught:
        reviewer.review(make_case())

    assert "sk-secret-123" not in str(caught.value)
    assert "***" in str(caught.value)
    assert caught.value.__cause__ is None  # the chained traceback would carry the key
    assert caught.value.__suppress_context__ is True


# --- settings -----------------------------------------------------------------------------


def test_model_is_required_and_the_error_names_the_variable():
    with pytest.raises(ConfigurationError, match="PR_INSPECTOR_MODEL"):
        ReviewerSettings.from_environment({})
    with pytest.raises(ConfigurationError, match="PR_INSPECTOR_MODEL"):
        ReviewerSettings.from_environment({"PR_INSPECTOR_MODEL": "   "})


def test_model_alone_means_a_local_model_with_the_default_timeout():
    settings = ReviewerSettings.from_environment({"PR_INSPECTOR_MODEL": "qwen2.5-coder:7b"})

    assert settings == ReviewerSettings(model="qwen2.5-coder:7b")
    assert settings.base_url is None and settings.api_key is None
    assert settings.timeout == DEFAULT_TIMEOUT_SECONDS


def test_pr_inspector_variables_win_over_the_openai_fallbacks():
    env = {
        "PR_INSPECTOR_MODEL": "m",
        "PR_INSPECTOR_BASE_URL": "https://primary.example/v1",
        "OPENAI_BASE_URL": "https://fallback.example/v1",
        "OPENAI_API_KEY": "fallback-key",
        "PR_BENCH_TIMEOUT": "90",
    }

    settings = ReviewerSettings.from_environment(env)

    assert settings.base_url == "https://primary.example/v1"
    assert settings.api_key == "fallback-key"
    assert settings.timeout == 90.0


@pytest.mark.parametrize("bad", ["abc", "0", "-5"])
def test_invalid_timeout_is_rejected(bad: str):
    with pytest.raises(ConfigurationError, match="PR_BENCH_TIMEOUT"):
        ReviewerSettings.from_environment({"PR_INSPECTOR_MODEL": "m", "PR_BENCH_TIMEOUT": bad})


def test_api_key_never_appears_in_the_settings_repr():
    settings = ReviewerSettings(model="m", api_key="sk-secret-123")

    assert "sk-secret-123" not in repr(settings)


def test_build_reviewer_wires_the_settings_into_pr_inspectors_reviewer():
    settings = ReviewerSettings(
        model="qwen2.5-coder:7b", base_url="http://localhost:11434/v1", timeout=120.0
    )

    reviewer = build_reviewer(settings)

    assert isinstance(reviewer, ReviewerPort)
    assert reviewer._reviewer.model == "qwen2.5-coder:7b"
    assert reviewer._reviewer.client.timeout == 120.0


# --- local or remote ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434/v1",
        "http://127.0.0.1:8000/v1",
        "http://[::1]:11434/v1",
        "http://ollama.localhost/v1",
    ],
)
def test_endpoints_on_this_machine_are_local(url: str):
    assert is_local_endpoint(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1",
        "http://192.168.1.5:11434/v1",  # another machine on the network is not local
        "http://localhost.evil.example/v1",  # a name that merely starts with "localhost"
        "",
    ],
)
def test_every_other_endpoint_is_remote(url: str):
    assert is_local_endpoint(url) is False


def test_a_reply_that_is_not_valid_json_is_a_per_case_failure_with_no_model_text():
    """Real case: the model wrapped its JSON in a code fence, and the SDK raised this error."""
    try:
        PrResult.model_validate_json('```json\n{"summary": "secret model text"}\n```')
    except ValidationError as exc:
        error = exc
    reviewer = PrInspectorReviewer(FakeInner(error))

    with pytest.raises(ReviewFailedError) as caught:
        reviewer.review(make_case())

    assert str(caught.value) == "the model's reply was not valid review JSON"
    assert "secret model text" not in str(caught.value)
