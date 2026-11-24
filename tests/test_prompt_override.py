"""Tests for the system prompt override and the fingerprint that run files record."""

import hashlib

import pr_inspector.infrastructure.llm.openai_client as client_module
import pytest

from pr_inspector_benchmark.domain.runs import RunInfo
from pr_inspector_benchmark.infrastructure.pr_inspector_reviewer import (
    default_system_prompt,
    prompt_fingerprint,
    system_prompt,
)


def test_the_fingerprint_is_the_first_ten_hex_characters_of_sha256():
    text = "You review diffs."

    assert prompt_fingerprint(text) == hashlib.sha256(text.encode()).hexdigest()[:10]


def test_the_override_is_used_inside_the_block_and_restored_after_it():
    original = default_system_prompt()

    with system_prompt("candidate prompt"):
        assert client_module.REVIEW_SYSTEM_PROMPT == "candidate prompt"

    assert client_module.REVIEW_SYSTEM_PROMPT == original


def test_the_original_prompt_is_restored_even_when_the_run_fails():
    original = default_system_prompt()

    with pytest.raises(RuntimeError):
        with system_prompt("candidate prompt"):
            raise RuntimeError("run failed")

    assert client_module.REVIEW_SYSTEM_PROMPT == original


@pytest.mark.parametrize("sha", ["NOTHEXHERE", "0123456789ab", "0123456"])
def test_a_run_records_only_a_well_formed_prompt_fingerprint(sha: str):
    with pytest.raises(ValueError, match="prompt_sha"):
        RunInfo(
            label="candidate-run",
            model="model",
            endpoint="local",
            started_at="2026-11-24T00:00:00+00:00",
            prompt_sha=sha,
        )
