# Fixtures

Each `*.json` file is one benchmark case: a real change from a public repository, plus the review outcome that counts as correct. `JsonFixtureLoader` validates every file, including a check that each expected issue points at lines that exist in the diff. Sources and licenses are in [ATTRIBUTION.md](ATTRIBUTION.md).

## How a fixture is built

- **Reversed fix.** A bug-fix commit or pull request is run backwards (`pr-bench build-fixture`), so the new side of the diff is the code *before* the fix and the bug appears as added lines. What the fix added shows up as deleted lines: the safeguard a reviewer should miss.
- **The fix does not explain itself.** Comment-only lines that the fix deleted are dropped, and the count is recorded in `provenance.construction`. Otherwise the diff would carry the fix's own explanation of the vulnerability, such as an advisory id, which no real review of the buggy change would contain. The deleted *code* stays.
- **Controls** have no expected issues and expect `LOW`. They are changes with no defect, and they measure false positives. One is a configuration-only change. The other is a fix commit taken forward, as merged, which pairs with its reversed bug fixture: a reviewer should flag the reversal and leave the fix alone.

## Expected issues

- Line numbers refer to the **new side** of the diff, the numbering pr-inspector reports.
- One expected issue per distinct code location where the defect lives: the added code, or for a deleted safeguard the context lines around where it was. A defect repeated at several places in one file is one issue with `extra_windows`.
- Only what the diff itself supports is labelled. A suspicious line that depends on code that is not in the diff is left out rather than guessed.

## Tags and risk levels

- `context` says how a reviewer could find the defect: `in_diff` (visible in the added lines), `removed_check` (the defect is a safeguard the diff deletes) or `needs_context` (it needs knowledge of code outside the diff). Results are broken down by it, to tell prompt problems from missing-context problems.
- `risk_level` is GitHub's advisory severity for security fixtures. For other bug fixes it is a judgement, explained in `rationale`.
