"""Domain exceptions for the benchmark."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pr_inspector_benchmark.domain.results import RawReply


class InvalidFixtureError(ValueError):
    """Raised when a fixture breaks one of the rules a valid benchmark case must satisfy."""


class FixtureLoadError(Exception):
    """Raised when a fixture file cannot be read, parsed or validated."""


class ReviewFailedError(Exception):
    """Raised by a reviewer when a review could not be completed (timeout, truncation, ...).

    Only this error is recorded against the case and the run goes on. Any other exception
    is a bug in the benchmark or the adapter and must not be hidden as a wrong answer.

    ``raw_reply`` is the model's reply when one was received, so a failed case can be diagnosed.
    """

    def __init__(self, message: str = "", *, raw_reply: "RawReply | None" = None) -> None:
        super().__init__(message)
        self.raw_reply = raw_reply


class ConfigurationError(Exception):
    """Raised when the benchmark is not configured well enough to run."""
