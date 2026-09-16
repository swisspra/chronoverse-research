# Answer-level pilot: results

> **STATUS · SUPERSEDED** — original dated 2026-09-13 02:36 · chain and replacements in [`00-START-HERE/VERSION-MAP.md`](../00-START-HERE/VERSION-MAP.md) · round 1; headline replaced by ROUND2-ANSWER-RESULTS.md, kept as the correction trail

Fifty questions, five retrieval arms, three repeats: 750 planned slots, all accounted for. The frozen model, prompt, contexts, expected answers, budgets and statistical definitions were committed before dispatch; nothing was changed after answers were seen. Transport stopped once on a 90.169 s timeout and was finished by a bounded continuation that dispatched only the 103 undispatched slots. That timeout is retained as an uncertain outcome and counts as a failure in every accuracy denominator: this is **not** a clean 750-response run.

Model `vertex_ai/gemini-3.8-flash`, temperature 0, reasoning effort low, completion limit 1,024 tokens, input limit 8,192 (16,384 for arm B). Manifest `e807eacb…`, prompt `3bb012d5…`, original checkpoint `547c173c…`. Audit: [answer-continuation-audit.json](answer-continuation-audit.json); summary: [answer-pilot-summary.json](answer-pilot-summary.json); amendment: [ANSWER-CONTINUATION-AMENDMENT.md](ANSWER-CONTINUATION-AMENDMENT.md).

## Arms

| | Retrieval layer |
| --- | --- |
| A | Vanilla RAG over chunks with dates written in the prose |
| B | Long context: every version of every relevant fact plus an explicit as-of instruction |
| C | Vanilla RAG plus cross-encoder reranking |
| D | Vanilla RAG plus a post-hoc metadata filter applied to retrieved results |
| E | Chronoverse tri-temporal projection (valid / known / received) |

## Primary table — frozen scoring, invalid attempts count as failures

| Arm | Valid completions | Closed-form accuracy | Support recovery | End-to-end recovery | Correct abstention | False abstention | Stale citations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 0.873 | 0.120 | 0.044 | 0.037 | 0.800 | 0.798 | 0.107 |
| B | 0.547 | 0.427 | 0.526 | 0.393 | 0.733 | 0.000 | 0.000 |
| C | 0.693 | 0.220 | 0.170 | 0.170 | 0.667 | 0.596 | 0.135 |
| D | 1.000 | 0.400 | 0.333 | 0.333 | 1.000 | 0.467 | 0.000 |
| **E** | 0.960 | **0.840** | **0.956** | **0.822** | **1.000** | **0.000** | **0.000** |

Denominators: accuracy 150 attempts per arm; support and end-to-end recovery 135 answerable attempts; correct abstention 15 unanswerable attempts; false abstention and citation audits use valid completed attempts only (A 119/131, B 71/82, C 94/104, D 135/150, E 129/144). Citation leakage of unreceived items is 0.000 in every arm; staleness is not.

## Preregistered contrasts, query-level pairing, 10,000 bootstrap replicates, seed 20260913

| Metric | E − A | E − B | E − C | E − D |
| --- | ---: | ---: | ---: | ---: |
| Closed-form accuracy | +0.720 [+0.660, +0.773] | +0.413 [+0.340, +0.487] | +0.620 [+0.533, +0.700] | +0.440 [+0.393, +0.493] |
| Support recovery | +0.911 [+0.852, +0.963] | +0.430 [+0.356, +0.511] | +0.785 [+0.696, +0.867] | +0.622 [+0.570, +0.682] |
| End-to-end recovery | +0.785 [+0.726, +0.837] | +0.430 [+0.356, +0.511] | +0.652 [+0.563, +0.733] | +0.489 [+0.437, +0.548] |
| Correct abstention | +0.200 [0.000, +0.467] | +0.267 [0.000, +0.533] | +0.333 [+0.067, +0.600] | 0.000 |
| False abstention | −0.833 [−0.933, −0.733] | 0.000 (13 pairs, descriptive) | −0.652 (23 pairs, descriptive) | −0.538 [−0.590, −0.487] |

Raw 95% percentile intervals shown; Bonferroni 98.75% intervals are in the summary file and exclude zero wherever the 95% interval does. Holm-adjusted sign-flip p = 2.0 × 10⁻⁴ for all four contrasts in closed-form accuracy, support recovery and end-to-end recovery, and for E − A and E − D in false abstention. **Correct abstention rests on 5 query pairs and is not significant** (Holm p ≈ 1.0 for E − A, E − B, E − D). False abstention for E − B and E − C falls below the 30-pair floor and is descriptive only, with complete-pair selection bias.

## The confound that has to be read with the table

Arms differ sharply in how often the model failed to produce a scorable answer: A 12.7%, B 45.3%, C 30.7%, D 0%, E 4.0%. Most of those are completion truncations against the 1,024-token limit, and B — which carries every version of every fact — truncates most. Under the frozen rule an invalid attempt is a failure, so part of E's margin over B and C is an instrument limit, not reasoning.

Among valid completions only, closed-form accuracy is A 0.137 (18/131), B 0.780 (64/82), C 0.317 (33/104), D 0.400 (60/150), E 0.875 (126/144). The ordering survives, and B moves from clearly behind to second — its earlier weakness was largely truncation. Any future round must raise the completion limit before repeating this comparison.

## What this establishes

At answer level, with one model and one prompt held fixed, tri-temporal retrieval produced markedly better answers than vanilla RAG, reranking, long context and a post-hoc metadata filter, on questions built around delivery, correction and retraction timing. Every contrast in the three main families clears its Bonferroni interval and Holm-adjusted threshold.

Two arms deserve their own note. **Arm D — the post-hoc metadata filter — was the strong classical control**, and it is the one that most directly tests the filter-order claim: it never failed a completion (150/150 valid) and never cited an unreceived or stale item, yet it recovered only 0.333 end-to-end against E's 0.822. Filtering retrieved output cannot restore a claim that a not-yet-delivered correction has already suppressed. **Arm B — long context with an explicit as-of instruction** — closed much of the gap when it completed, which is the honest counter-evidence: given the whole history and enough output budget, a capable model does a fair amount of this reasoning in context, at roughly 4× the tokens per answered question (15,114 vs 3,567).

## What it does not establish

Fifty synthetic questions authored in this repository are not fifty independent real-world samples, and three repeats measure variability, not power. One model, one provider, one prompt. The dispatch gap and the separate continuation phase are confounded with question and time, so no timing comparison is claimed. Citation leakage of 0.000 in arms that failed many completions is not evidence of clean behaviour — the failed fraction is reported beside it for that reason. Private-provider dollar rates are unknown; observed usage is 2,524,970 input and 444,230 completion tokens, with one attempt's usage permanently unknown.

Reproduce:

```bash
.bench-venv/bin/python -m benchmarks.verify_answer_continuation \
  --manifest docs/benchmarks-next/answer-contexts-50.jsonl.gz \
  --prompt docs/benchmarks-next/answer-prompt-v2.txt \
  --original docs/benchmarks-next/answer-pilot-original-checkpoint.json \
  --continuation docs/benchmarks-next/answer-continuation-results.json \
  --union docs/benchmarks-next/answer-pilot-union.json

.bench-venv/bin/python -m benchmarks.aggregate_answer_continuation \
  --manifest docs/benchmarks-next/answer-contexts-50.jsonl.gz \
  --prompt docs/benchmarks-next/answer-prompt-v2.txt \
  --original docs/benchmarks-next/answer-pilot-original-checkpoint.json \
  --continuation docs/benchmarks-next/answer-continuation-results.json \
  --union docs/benchmarks-next/answer-pilot-union.json \
  --frozen-root .runtime/answer-pilot-analysis-run \
  --output <new-path>.json
```
