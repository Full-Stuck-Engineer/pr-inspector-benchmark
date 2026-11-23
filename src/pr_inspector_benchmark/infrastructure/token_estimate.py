"""Estimates the input tokens a review sends, from the diff itself.

A cloud endpoint's reported prompt count includes roughly 2,000 to 9,000 tokens per request that
the benchmark never sent, so that count cannot be used for pricing. This estimate counts the text
the model actually reads: the system prompt, the annotated diff, and the JSON schema, which the
cloud endpoint counts as input (about 650 tokens) and the local endpoint does not.

The divisor is calibrated on local Qwen counts for the approved fixtures, where the system prompt
and annotated diff averaged about 3.5 characters per token. A different tokenizer can differ from
that by roughly 10%.
"""

import json
import math

from pr_inspector.domain.entities import PRReviewResult
from pr_inspector.infrastructure.git.diff_extractor import GitCliDiffProvider
from pr_inspector.infrastructure.llm.openai_client import REVIEW_SYSTEM_PROMPT

CHARS_PER_TOKEN = 3.5
_SCHEMA_TEXT = json.dumps(PRReviewResult.model_json_schema())
_DIFF_PARSER = GitCliDiffProvider()  # only parse_unified_diff is used; no git command runs


def estimate_text_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def estimate_input_tokens(diff: str) -> int:
    """Tokens of the system prompt, the review request built from ``diff``, and the schema."""
    annotated = "\n\n".join(
        file_diff.annotated_diff_text
        for file_diff in _DIFF_PARSER.parse_unified_diff(diff)
        if file_diff.hunks
    )
    if not annotated.strip():
        annotated = "No code hunk changes found in diff."
    request = f"Review the following code diff:\n\n{annotated}"
    return (
        estimate_text_tokens(REVIEW_SYSTEM_PROMPT)
        + estimate_text_tokens(request)
        + estimate_text_tokens(_SCHEMA_TEXT)
    )
