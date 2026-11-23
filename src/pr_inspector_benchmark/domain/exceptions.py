"""Domain exceptions for the benchmark."""


class InvalidFixtureError(ValueError):
    """Raised when a fixture breaks one of the rules a valid benchmark case must satisfy."""


class FixtureLoadError(Exception):
    """Raised when a fixture file cannot be read, parsed or validated."""


class ReviewFailedError(Exception):
    """Raised by a reviewer when a review could not be completed (timeout, truncation, ...).

    Only this error is recorded against the case and the run goes on. Any other exception
    is a bug in the benchmark or the adapter and must not be hidden as a wrong answer.
    """
