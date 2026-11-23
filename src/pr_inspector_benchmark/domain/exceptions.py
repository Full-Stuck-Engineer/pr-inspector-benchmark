"""Domain exceptions for the benchmark."""


class InvalidFixtureError(ValueError):
    """Raised when a fixture breaks one of the rules a valid benchmark case must satisfy."""


class FixtureLoadError(Exception):
    """Raised when a fixture file cannot be read, parsed or validated."""
