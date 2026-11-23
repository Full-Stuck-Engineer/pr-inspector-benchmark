# Results: local vs cloud, first comparison

Three runs per arm on the 17 approved fixtures, run on 2026-11-23. The numbers are the mean of the three runs, with the range in brackets. Every figure comes from the result files of these six runs.

## Setup

- **Fixtures:** 17 real changes with a known defect or none. Nine are security fixes from GitHub advisories, six are non-security bug fixes, and two are controls with no defect. They hold 22 expected issues in total. Each fixture is a reversed fix; see [fixtures/README.md](fixtures/README.md).
- **Local arm:** `qwen2.5-coder:7b` served by Ollama with a 16k context window, on an Apple M4 with 16 GB of memory. Priced at $0.
- **Cloud arm:** a cloud model behind an OpenAI-compatible router. The model name is withheld. Priced at the DeepSeek V4.1 Flash list price for peak hours, $0.30 per million input tokens and $1.20 per million output tokens, as a proxy. Off-peak is half of that. Source: [DeepSeek API pricing](https://api-docs.deepseek.com/quick_start/pricing).
- **Same reviewer for both arms:** pr-inspector's reviewer, with the same prompt and output schema.

## How tokens are counted

A cloud endpoint's own prompt count includes roughly 110,000 to 135,000 tokens per run that the benchmark never sends. Remote runs are therefore priced on an estimate of what the model reads: the system prompt, the annotated diff and the JSON schema. That estimate is 23,754 input tokens per run. Against the local Qwen counts it is within 0.3% (15,900 estimated against 15,858 reported). The schema part of the estimate is about 190 tokens per request lower than the endpoint's own count, so the estimate may be slightly low. Each run file stores both the reported and the estimated count.

## Summary

| Metric | Local | Cloud |
|---|---|---|
| Issues found | 9 of 22 (41%) | 19.3 of 22 (88%) [16–21] |
| Precision | 60% | 89% [86–91%] |
| False alarms | 6 | 5 [4–6] |
| Risk level exact | 6 of 17 (35%) | 7.3 of 17 (43%) [7–8] |
| Risk level within one step | 12 of 17 (71%) | 15 of 17 (88%) [14–16] |
| Controls flagged | 2 of 2 (every run) | 0 of 2 (every run) |
| Recall, in the diff | 3 of 7 (43%) | 6.7 of 7 (95%) [6–7] |
| Recall, a removed check | 6 of 12 (50%) | 10 of 12 (83%) [8–11] |
| Recall, needs context | 0 of 3 (0%) | 2.7 of 3 (89%) [2–3] |
| Input tokens, cost basis | 15,858 | 23,754 |
| Output tokens | 2,679 | 13,791 [11,010–15,778] |
| Cost | $0 | $0.024 [$0.020–0.026] |
| Mean time per fixture | 12.6 s [12.4–12.7] | 26.8 s [17.7–34.8] |

## Per run

| | Local run 1 / 2 / 3 | Cloud run 1 / 2 / 3 |
|---|---|---|
| Issues found | 9 / 9 / 9 of 22 | 21 / 16 / 21 of 22 |
| False alarms | 6 / 6 / 6 | 5 / 6 / 4 |
| Risk level exact | 6 / 6 / 6 of 17 | 8 / 7 / 7 of 17 |
| Output tokens | 2,679 / 2,679 / 2,679 | 11,010 / 15,778 / 14,584 |
| Cost | $0 / $0 / $0 | $0.0203 / $0.0261 / $0.0246 |

The three local runs are identical, as expected for a deterministic setting. The cloud runs are not.

## What it shows

- **The cloud arm found more of the real issues in every run**: 16 to 21 of 22, against 9 for the local arm.
- **Neither arm often gets the exact risk level right.** Local is at 35% and cloud at 41% to 47%. Cloud is usually within one step, 14 to 16 of 17.
- **Clean code is flagged by the local arm in every run.** The cloud arm flagged none of the two controls in its three runs. An earlier cloud run, made before the billing fix with the same prompts, flagged both. The control result is therefore not stable.
- **Cloud results vary from run to run**, from 16 to 21 issues found. One run cannot rank the two models. Local results do not vary.
- **The needs-context group is too small to conclude anything.** It has three fixtures, so it cannot yet settle the Phase 2 question.

## Limitations

- 17 fixtures and 22 expected issues. One issue is 4.5 percentage points, so the differences need more fixtures to be firm.
- Most of the repositories are well known and their fixes are public, so the models may have seen them during training.
- The risk levels for the non-security fixtures and the controls are judgements. The security fixtures use GitHub's advisory severity.
- The cloud cost uses a proxy price and an estimated token count. The router's actual bill is not known.
- Three runs per arm, with no statistical test.
- A reply that cannot be parsed is recorded as a failed case, not a wrong answer. No case failed in these six runs.

## Reproduce

```
uv sync --locked
OLLAMA_CONTEXT_LENGTH=16384 ollama serve
uv run pr-bench run --label local-qwen --model qwen2.5-coder:7b --base-url http://localhost:11434/v1
uv run pr-bench run --label cloud-bantai --model <model> --base-url <url> --api-key-env <VARIABLE> --price-in 0.30 --price-out 1.20
uv run pr-bench compare results/local-qwen.json results/cloud-bantai.json
```

Run files are written to `results/`, which is git-ignored. Related: the code-fence crash found in this comparison is tracked in [pr-inspector#33](https://github.com/Full-Stuck-Engineer/pr-inspector/issues/33).
