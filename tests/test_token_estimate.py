"""The estimate of the input tokens a review sends, from the diff."""

from pr_inspector_benchmark.infrastructure.token_estimate import (
    CHARS_PER_TOKEN,
    estimate_input_tokens,
    estimate_text_tokens,
)

SMALL = """\
diff --git a/app/db.py b/app/db.py
--- a/app/db.py
+++ b/app/db.py
@@ -1 +1 @@
-x = 1
+x = 2
"""


def large_diff(lines: int) -> str:
    body = "".join(f"+value_{n} = compute({n}) + offset_{n}\n" for n in range(lines))
    return (
        "diff --git a/app/big.py b/app/big.py\n--- a/app/big.py\n+++ b/app/big.py\n"
        f"@@ -0,0 +1,{lines} @@\n" + body
    )


def test_text_tokens_round_up_by_the_calibrated_divisor():
    assert estimate_text_tokens("") == 0
    assert estimate_text_tokens("a" * 3) == 1  # 3 / 3.5 rounds up
    assert estimate_text_tokens("a" * 35) == 10
    assert CHARS_PER_TOKEN == 3.5


def test_a_bigger_diff_is_estimated_as_more_tokens():
    assert estimate_input_tokens(large_diff(200)) > estimate_input_tokens(large_diff(20))


def test_the_estimate_includes_the_system_prompt_and_the_schema():
    # A diff with no reviewable hunks still costs the fixed parts of every request.
    empty = estimate_input_tokens("")

    assert empty > 400  # the system prompt and the JSON schema alone are several hundred tokens


def test_a_diff_with_no_hunks_uses_the_same_fallback_text_as_pr_inspector():
    assert estimate_input_tokens("") == estimate_input_tokens("not a diff at all")


def test_a_real_small_change_is_estimated_close_to_its_fixed_overhead_plus_content():
    assert estimate_input_tokens(SMALL) > estimate_input_tokens("")
