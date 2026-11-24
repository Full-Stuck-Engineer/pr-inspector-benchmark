"""Adapter that lets the benchmark review fixtures with pr-inspector.

pr-inspector's types stop at this module: the domain only sees its own outcome and telemetry.
"""

import hashlib
import json
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlparse

import pr_inspector.infrastructure.llm.openai_client as client_module
from pr_inspector.domain.exceptions import ReviewExecutionError
from pr_inspector.domain.protocols import LLMReviewer
from pr_inspector.infrastructure.git.diff_extractor import GitCliDiffProvider
from pr_inspector.infrastructure.llm.openai_client import OpenAICompatibleLLMReviewer
from pydantic import ValidationError

from pr_inspector_benchmark.domain.entities import BenchmarkCase, RiskLevel
from pr_inspector_benchmark.domain.exceptions import ConfigurationError, ReviewFailedError
from pr_inspector_benchmark.domain.results import RawReply, ReportedIssue, ReviewOutcome, Telemetry

# pr-inspector's own default is 60 s, below what a local model needs for a large fixture.
DEFAULT_TIMEOUT_SECONDS = 180.0

# Longest reply kept for a failed case. It bounds the size of a run file.
REPLY_CHARACTER_LIMIT = 20_000

# The last HTTP reply seen by the current thread. The SDK sends and receives in the same
# thread, so the hook below records the reply belonging to the review running in that thread.
_capture = threading.local()


def _record_reply(response) -> None:
    """httpx response hook: keep the status, finish reason and text of the latest reply."""
    response.read()
    try:
        choice = json.loads(response.content)["choices"][0]
        _capture.reply = {
            "status": response.status_code,
            "finish_reason": choice.get("finish_reason"),
            "content": (choice["message"].get("content") or "")[:REPLY_CHARACTER_LIMIT],
        }
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        _capture.reply = {
            "status": response.status_code,
            "note": "reply was not in chat-completion format",
            "content": response.text[:REPLY_CHARACTER_LIMIT],
        }


def _install_reply_capture(inner: OpenAICompatibleLLMReviewer) -> None:
    """Hook the SDK's HTTP client. ``_client`` is private to the SDK, so a test pins it."""
    inner.client._client.event_hooks["response"].append(_record_reply)


def prompt_fingerprint(text: str) -> str:
    """The first 10 hex characters of the SHA-256 of a system prompt, as run files store it."""
    return hashlib.sha256(text.encode()).hexdigest()[:10]


def default_system_prompt() -> str:
    """pr-inspector's own system prompt, as this installation has it."""
    return client_module.REVIEW_SYSTEM_PROMPT


@contextmanager
def system_prompt(text: str) -> Iterator[None]:
    """Use ``text`` as pr-inspector's system prompt, then put the previous one back.

    pr-inspector reads its prompt from a module constant at call time, so this is the seam.
    """
    original = client_module.REVIEW_SYSTEM_PROMPT
    client_module.REVIEW_SYSTEM_PROMPT = text
    try:
        yield
    finally:
        client_module.REVIEW_SYSTEM_PROMPT = original


class PrInspectorReviewer:
    """``ReviewerPort`` backed by a pr-inspector reviewer."""

    def __init__(self, reviewer: LLMReviewer, secrets: Sequence[str] = ()) -> None:
        self._reviewer = reviewer
        self._secrets = tuple(secret for secret in secrets if secret)
        # Only parse_unified_diff is used; it runs no git command.
        self._diff_parser = GitCliDiffProvider()

    def review(self, case: BenchmarkCase) -> tuple[ReviewOutcome, Telemetry]:
        file_diffs = self._diff_parser.parse_unified_diff(case.diff)
        _capture.reply = None
        try:
            result, telemetry = self._reviewer.review(file_diffs)
        except ReviewExecutionError as exc:
            # `from None`: the chained traceback would carry the unredacted message.
            raise ReviewFailedError(self._redact(str(exc)), raw_reply=self._captured()) from None
        except ValidationError:
            # The model's reply did not match the schema, for example JSON inside a code fence.
            # The SDK raises this itself, outside pr-inspector's handling, and it must be a
            # per-case failure rather than the end of the whole run. The message is generic;
            # the reply itself is kept apart, as raw_reply, after redaction.
            raise ReviewFailedError(
                "the model's reply was not valid review JSON", raw_reply=self._captured()
            ) from None

        outcome = ReviewOutcome(
            risk_level=RiskLevel(result.risk_level.value),
            issues=tuple(
                ReportedIssue(
                    file_path=issue.file_path,
                    line_number=issue.line_number,
                    severity=RiskLevel(issue.severity.value),
                    title=issue.title,
                )
                for issue in result.issues
            ),
        )
        return outcome, Telemetry(
            model=telemetry.model,
            input_tokens=telemetry.input_tokens,
            output_tokens=telemetry.output_tokens,
            latency_ms=telemetry.latency_ms,
        )

    def _redact(self, text: str) -> str:
        """Provider errors can echo a key; results are published, so a key must never survive."""
        for secret in self._secrets:
            text = text.replace(secret, "***")
        return text

    def _captured(self) -> RawReply | None:
        """The reply received for the review that just failed, redacted, if there was one."""
        reply = getattr(_capture, "reply", None)
        if reply is None:
            return None
        return RawReply(
            status=reply["status"],
            finish_reason=reply.get("finish_reason"),
            content=self._redact(reply.get("content", "")),
            note=reply.get("note"),
        )


@dataclass(frozen=True)
class ReviewerSettings:
    """How to reach the model under test. The key never appears in ``repr``."""

    model: str
    base_url: str | None = None
    api_key: str | None = field(default=None, repr=False)
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> "ReviewerSettings":
        """Read the settings pr-inspector itself uses.

        The model is required: the benchmark exists to compare models, so it never guesses one.
        With neither a base URL nor a key, pr-inspector talks to a local Ollama.
        """
        model = env.get("PR_INSPECTOR_MODEL", "").strip()
        if not model:
            raise ConfigurationError(
                "PR_INSPECTOR_MODEL is not set. Name the model to benchmark, "
                "for example qwen2.5-coder:7b for a local Ollama."
            )
        return cls(
            model=model,
            base_url=env.get("PR_INSPECTOR_BASE_URL") or env.get("OPENAI_BASE_URL") or None,
            api_key=env.get("PR_INSPECTOR_API_KEY") or env.get("OPENAI_API_KEY") or None,
            timeout=_parse_timeout(env.get("PR_BENCH_TIMEOUT")),
        )


def _parse_timeout(raw: str | None) -> float:
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        timeout = float(raw)
    except ValueError:
        timeout = 0.0
    if timeout <= 0:
        raise ConfigurationError(f"PR_BENCH_TIMEOUT must be a positive number of seconds: {raw!r}")
    return timeout


def is_local_endpoint(base_url: str) -> bool:
    """Whether an endpoint runs on this machine, so it needs no key and costs nothing."""
    host = urlparse(base_url).hostname or ""
    return host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".localhost")


def build_reviewer(settings: ReviewerSettings) -> PrInspectorReviewer:
    """Composition helper: a pr-inspector reviewer wired from the settings."""
    inner = OpenAICompatibleLLMReviewer(
        base_url=settings.base_url,
        api_key=settings.api_key,
        model=settings.model,
        timeout=settings.timeout,
    )
    _install_reply_capture(inner)
    return PrInspectorReviewer(inner, secrets=(settings.api_key or "",))
