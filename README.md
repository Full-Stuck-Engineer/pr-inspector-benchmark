# pr-inspector-benchmark

Benchmark harness for [pr-inspector](https://github.com/Full-Stuck-Engineer/pr-inspector).
It answers one question with numbers: **how accurately, how fast, and at what cost does a given
LLM review real code changes?**

> **Status:** bootstrapping. Nothing is implemented yet; the work is tracked in the
> [issues](https://github.com/Full-Stuck-Engineer/pr-inspector-benchmark/issues).

## Why this exists

pr-inspector's Phase 1 exit criteria require the tool to be "benchmarked on 5–10 historical
PRs/commits with documented accuracy vs. cost/latency notes". Two later decisions also depend on
having a labelled fixture set:

- **Prompt tuning.** The false-positive rate cannot be measured without known-good labels.
- **Phase 2 (codebase RAG).** Moving to retrieval only makes sense once the benchmark shows that
  missing codebase context, not the prompt or the model, is the bottleneck.

## What it measures

| Metric | Definition |
|---|---|
| Risk accuracy (exact) | Predicted `risk_level` equals the expected level |
| Risk accuracy (near) | Predicted `risk_level` is within one level of the expected one (ordinal tolerance) |
| Issue recall | Share of expected issues that were reported (same file, line inside the expected window) |
| False positives | Reported issues that match no expected issue |
| Tokens | Input and output tokens per fixture |
| Latency | Wall-clock milliseconds per fixture |
| Cost | Estimated spend from a configurable per-model price table (zero for local models) |

## How fixtures are built

Each fixture is a real historical change with a known defect. Fixtures are built by **reversing a
bug-fix commit**: the reversed diff re-introduces the bug, and the fix commit's description tells
us which issue a good reviewer should flag and how severe it is.

Every fixture records its provenance (repository, commit, construction method) next to the diff
and the expected findings. Only public sources with a compatible license are accepted.

## Models compared

| Arm | Example | Purpose |
|---|---|---|
| Local | `qwen2.5-coder:7b` via [Ollama](https://ollama.com) | Zero-cost, private baseline |
| Cloud | any OpenAI-compatible endpoint (OpenAI, Gemini) | Accuracy ceiling and cost reference |

Both arms are driven through pr-inspector's OpenAI-compatible client, so the same fixtures and
the same prompt are used for every model.

## Planned layout

The harness follows the same Clean Architecture boundaries as pr-inspector.

```
src/pr_inspector_benchmark/
├── domain/           # BenchmarkCase, ExpectedIssue, scores, protocols (no third-party imports)
├── application/      # RunBenchmarkUseCase, scoring
├── infrastructure/   # fixture loader, pr-inspector adapter, JSON / Markdown reporters
└── interface/        # CLI
fixtures/             # one JSON file per historical change
```

## Local setup notes (Ollama)

On machines with 16 GB or less, Ollama defaults to a 4k-token context window, and prompts longer
than the window are truncated by the server. Realistic diffs need more, so start the server with
a larger context:

```bash
OLLAMA_CONTEXT_LENGTH=16384 OLLAMA_FLASH_ATTENTION=1 ollama serve
ollama pull qwen2.5-coder:7b
```

pr-inspector reads its model settings from `PR_INSPECTOR_BASE_URL`, `PR_INSPECTOR_API_KEY` and
`PR_INSPECTOR_MODEL` (falling back to `OPENAI_BASE_URL` and `OPENAI_API_KEY`):

```bash
export PR_INSPECTOR_BASE_URL="http://localhost:11434/v1"
export PR_INSPECTOR_API_KEY="ollama"
export PR_INSPECTOR_MODEL="qwen2.5-coder:7b"
```

## Contributing

- **Issue first.** No code without a GitHub issue describing the objective and acceptance criteria.
- **Small commits.** At most 400 changed lines per commit; fixtures and lockfiles are excluded
  from that count.
- **Conventional Commits.** `<type>(<scope>): <subject> (refs #<issue>)`.
- Quality gates: `uv run pytest` and `uv run ruff check .` / `uv run ruff format --check .`.

## License

Apache License 2.0. See [LICENSE](LICENSE).
