"""The settings of a benchmark run, and what it cost."""

import re
from dataclasses import dataclass

from pr_inspector_benchmark.domain.entities import is_valid_case_id

ENDPOINTS = ("local", "remote")


@dataclass(frozen=True)
class RunInfo:
    """What was run: one model on one endpoint.

    Only whether the endpoint is local or remote is kept, never its address, because results
    are published and an address can be private. Prices are USD per million tokens.
    """

    label: str  # also the results file name, so it must be a slug
    model: str
    endpoint: str
    started_at: str
    line_tolerance: int = 0
    price_in: float | None = None
    price_out: float | None = None
    prompt_sha: str | None = None  # fingerprint of the system prompt that was used

    def __post_init__(self) -> None:
        if not is_valid_case_id(self.label):
            raise ValueError(
                f"label must be a lowercase slug (letters, digits, '-', '_'): {self.label!r}"
            )
        if self.prompt_sha is not None and not re.fullmatch(r"[0-9a-f]{10}", self.prompt_sha):
            raise ValueError("prompt_sha must be 10 lowercase hex characters")
        if not self.model.strip():
            raise ValueError("model must not be blank")
        if self.endpoint not in ENDPOINTS:
            raise ValueError(f"endpoint must be one of {ENDPOINTS}: {self.endpoint!r}")
        if self.line_tolerance < 0:
            raise ValueError("line_tolerance must not be negative")
        if any(price is not None and price < 0 for price in (self.price_in, self.price_out)):
            raise ValueError("prices must not be negative")

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float | None:
        """The cost of the given tokens, or None when either price is unknown.

        An unknown price is not a free run: it must show up as unknown, never as 0.
        """
        if self.price_in is None or self.price_out is None:
            return None
        return (input_tokens * self.price_in + output_tokens * self.price_out) / 1_000_000


def billed_input_tokens(endpoint: str, reported: int, estimated: int | None) -> int:
    """The input tokens a run is priced on.

    A local model's own tokenizer counts its input, so its reported count is used. A remote
    endpoint's reported count includes tokens that were never sent (measured at roughly 2,000 to
    9,000 extra per request on the cloud arm), so the estimate of what the model reads is used.
    """
    if endpoint == "local":
        return reported
    if estimated is None:
        raise ValueError("a remote run is priced on estimated input tokens, so it needs them")
    return estimated
