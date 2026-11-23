"""The rule that decides which input token count a run is priced on."""

import pytest

from pr_inspector_benchmark.domain.runs import billed_input_tokens


def test_a_local_run_is_priced_on_its_reported_count():
    assert billed_input_tokens("local", reported=15_858, estimated=None) == 15_858


def test_a_local_run_ignores_any_estimate():
    assert billed_input_tokens("local", reported=3000, estimated=99) == 3000


def test_a_remote_run_is_priced_on_the_estimate_not_the_reported_count():
    assert billed_input_tokens("remote", reported=148_479, estimated=23_754) == 23_754


def test_a_remote_run_without_an_estimate_cannot_be_priced():
    with pytest.raises(ValueError, match="estimated input tokens"):
        billed_input_tokens("remote", reported=10, estimated=None)
