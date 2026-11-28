"""The real pr-inspector client, driven through the adapter against a fake endpoint.

The benchmark's failed-case counts depend on how pr-inspector reads a reply. These tests pin
that: a fenced reply is parsed, a reply that breaks the review schema gets one retry, the
raw reply of a case that still fails is kept, and a candidate prompt reaches the request.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pr_inspector_benchmark.domain.entities import (
    BenchmarkCase,
    ContextNeeded,
    ExpectedIssue,
    Provenance,
    RiskLevel,
)
from pr_inspector_benchmark.domain.exceptions import ReviewFailedError
from pr_inspector_benchmark.infrastructure.pr_inspector_reviewer import (
    ReviewerSettings,
    build_reviewer,
    system_prompt,
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

REVIEW = {
    "summary": "Query built from user input.",
    "risk_level": "HIGH",
    "issues": [
        {
            "file_path": "app/db.py",
            "line_number": 11,
            "severity": "HIGH",
            "title": "SQL injection",
            "description": "User input is concatenated into the query.",
        }
    ],
}


def make_case() -> BenchmarkCase:
    return BenchmarkCase(
        id="sql-injection-example",
        description="Query built from user input",
        language="python",
        context=ContextNeeded.IN_DIFF,
        provenance=Provenance("example/project", "MIT", "abc123", "https://example.test", "rev"),
        diff=DIFF,
        expected_risk=RiskLevel.HIGH,
        rationale="Attacker-controlled input reaches the query.",
        expected_issues=(ExpectedIssue("app/db.py", 11, 12, "SQL built by concatenation"),),
    )


class FakeEndpoint:
    """An OpenAI-compatible endpoint that answers each request with the next canned reply."""

    def __init__(self, *contents: str) -> None:
        self.contents = list(contents)
        self.requests: list[dict] = []
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers["Content-Length"]))
                endpoint.requests.append(json.loads(body))
                content = endpoint.contents.pop(0)
                reply = {
                    "id": "c",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "m",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                }
                data = json.dumps(reply).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "FakeEndpoint":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()

    def reviewer(self):
        port = self._server.server_address[1]
        settings = ReviewerSettings(
            model="m", base_url=f"http://127.0.0.1:{port}/v1", api_key="test-key-123", timeout=10
        )
        return build_reviewer(settings)


def test_a_fenced_reply_costs_one_retry():
    # The SDK parses the reply itself and raises on the fence before pr-inspector's own
    # fence handling runs, so pr-inspector treats it as a schema violation and retries.
    # If pr-inspector starts parsing fences directly, this sees one request and fails:
    # update it then, because run files from before and after are not comparable.
    fenced = "```json\n" + json.dumps(REVIEW) + "\n```"
    with FakeEndpoint(fenced, json.dumps(REVIEW)) as endpoint:
        outcome, _ = endpoint.reviewer().review(make_case())

    assert outcome.risk_level is RiskLevel.HIGH
    assert [issue.line_number for issue in outcome.issues] == [11]
    assert len(endpoint.requests) == 2


def test_an_empty_reply_is_retried_once():
    with FakeEndpoint("", json.dumps(REVIEW)) as endpoint:
        outcome, _ = endpoint.reviewer().review(make_case())

    assert outcome.risk_level is RiskLevel.HIGH
    assert len(endpoint.requests) == 2


def test_a_reply_that_fails_twice_keeps_its_raw_reply():
    broken = json.dumps({**REVIEW, "issues": [{**REVIEW["issues"][0], "line_number": None}]})
    with FakeEndpoint(broken, broken) as endpoint:
        with pytest.raises(ReviewFailedError) as caught:
            endpoint.reviewer().review(make_case())

    assert len(endpoint.requests) == 2
    assert caught.value.raw_reply.finish_reason == "stop"
    assert caught.value.raw_reply.content == broken


def test_a_candidate_prompt_reaches_the_request():
    with FakeEndpoint(json.dumps(REVIEW)) as endpoint, system_prompt("CANDIDATE PROMPT"):
        endpoint.reviewer().review(make_case())

    assert endpoint.requests[0]["messages"][0] == {
        "role": "system",
        "content": "CANDIDATE PROMPT",
    }
