# Round 2 answer experiment: fair baselines, three answerers

Round 1 compared five arms where the vanilla arms ranked with bare MiniLM cosine and the
Chronoverse arms ranked with the application's hybrid lexical/vector/graph score. An external
review identified that as a confound: part of the measured advantage was retrieval quality, not
temporal semantics. Round 2 removes it, adds two controls, and repeats the comparison on three
answerer models.

## What changed from round 1

- **A2** replaces A: the vanilla RAG arm now ranks with `0.35 × lexical + 0.65 × cosine`, the same
  lexical signal the application uses, renormalised without the graph term it cannot compute.
- **C2** replaces C: A2's top-50 reordered by the same local cross-encoder.
- **D2** is new: delivery projection at assertion level — lifecycle computed only from notices the
  recipient actually received. It separates the clock from the item view.
- **Z** is new: no retrieval at all, the floor.
- **D** is unchanged but relabelled honestly: ledger-global lifecycle projection followed by a
  delivery post-filter. Its eligibility uses corrections the ledger knows even when the recipient
  has not received them, which is also how a conventional bitemporal store behaves.
- Completion budget raised from 1,024 to 4,096 tokens. Every arm now completes 100% of attempts;
  round 1 lost 12–45% of attempts per arm to truncation.

Contexts: `answer-contexts-v2-50.jsonl.gz` (tracked gzipped; the 152 MB expansion stays local), manifest sha256 `ae660b207700d6db698ab3435f6e67c8fc6ed41cb90e43973a9beacec3dfd3c0`,
50 questions × 7 arms = 350 rows. Prompt unchanged from round 1 (`answer-prompt-v2.txt`), so the two
rounds remain comparable. Gold is attached only after every arm's context is assembled.

## Closed-form accuracy

Share of attempts whose answer contains every expected value. Denominator is every dispatched slot.

| Arm | System | Gemini 3.8 Flash | Claude Haiku 4.5 | GPT-5-mini |
| --- | --- | ---: | ---: | ---: |
| Z | no retrieval | 10.0% | 4.7% | 10.0% |
| D | global lifecycle + post-filter | 40.0% | 30.0% | 40.0% |
| A2 | RAG, lexical + dense | 59.0% | 54.0% | 54.0% |
| C2 | RAG + cross-encoder | 67.0% | 62.7% | 62.0% |
| D2 | delivery projection | 78.0% | 68.7% | 78.0% |
| B | long context, every version | 88.0% | 78.7% | 78.0% |
| **E** | **delivery + item view** | **88.0%** | **78.7%** | **88.7%** |

## End-to-end correctness

Right answer, every required support group cited, and nothing cited that the recipient had not
received or that was already superseded. Answerable questions only.

| Arm | Gemini 3.8 Flash | Claude Haiku 4.5 | GPT-5-mini | Stale citations (range) |
| --- | ---: | ---: | ---: | ---: |
| A2 | 41.1% | 43.0% | 2.2% | 24–80% |
| C2 | 51.1% | 47.4% | 2.2% | 24–85% |
| D | 33.3% | 33.3% | 33.3% | 0% |
| D2 | 75.6% | 75.6% | 75.6% | 0% |
| B | 85.6% | 79.3% | 11.9% | 1–82% |
| **E** | **86.7%** | **87.4%** | **87.4%** | **0%** |

## Head to head against long context

E minus B, percentage points.

| Measure | Gemini 3.8 Flash | Claude Haiku 4.5 | GPT-5-mini |
| --- | ---: | ---: | ---: |
| Closed-form accuracy | 0.0 | 0.0 | +10.7 |
| End-to-end correctness | +1.1 | +8.1 | +75.5 |
| Support recovery | 0.0 | +3.0 | +1.5 |
| Stale citations (lower better) | −1.0 | −6.7 | −82.0 |
| Tokens per answered question | −59% | −55% | −59% |

Mean total tokens per answered request: E 3,086 / 2,931 / 2,258 against B 7,607 / 6,511 / 5,552.

## What this round establishes

The post-filter control loses by 48 points of accuracy on every model. Filtering a conventional
system's output afterwards does not restore a claim that an undelivered correction has already
suppressed, and that now holds at answer level, not only in retrieval.

The three time-aware arms never cite superseded evidence — 0% in every model, every repeat — while
plain and reranked RAG do so in 24–85% of answers. GPT-5-mini is the stress case: it cites
aggressively, so a context without a delivery clock collapses its end-to-end score from 78.0%
accuracy to 11.9%, while the delivery arm holds at 87.4%.

The item view accounts for about ten points: E beats D2 by +10.0 / +10.0 / +10.7. That gap is a
capability difference in what can be returned, not the clock.

## What this round does not establish

Long context is not beaten on raw accuracy. Two of three models tie exactly (88.0 and 78.7). What
survives across every model is citation discipline and token cost, not answer correctness alone.

Abstention is a property of the answerer here, not of retrieval: with Haiku no arm abstains
correctly except D2 at 6.7%; with Gemini and GPT-5-mini the time-aware arms reach 100%.

Round 1's headline was inflated. The vanilla arm scored 12.0% then and 54–59% once given the same
lexical signal, so most of that margin was retrieval quality. The round-1 numbers remain published
unchanged; this round supersedes their interpretation, not their record.

Fifty synthetic questions authored in this repository are not fifty independent real-world samples,
the entity names are near-duplicates by construction, and one answerer ran two repeats rather than
three.

## Transport record

| Model | Slots | Repeats | Status |
| --- | ---: | ---: | --- |
| `vertex_ai/gemini-3.8-flash` (internal proxy) | 700 of 1,050 | 0, 1 | interrupted when the machine slept; one dispatched slot has an unknown outcome and is excluded |
| `anthropic/claude-haiku-4.5` | 1,050 | 0, 1, 2 | complete |
| `openai/gpt-5-mini` | 1,050 | 0, 1, 2 | complete |

Earlier aborted attempts against the same manifest are retained privately: two runs stopped on an
uncertain transport outcome after 53 and 14 slots, and a third after 369 and 422 slots. None of
their answers are scored here.

**The internal proxy substitutes models.** Requests for `claude-sonnet-5`, `gpt-5.6-terra`,
`Claude Haiku 4.5`, `vertex_ai/claude-opus-5`, `dashscope/qwen3.8-max`, `glm-5.2` and
`dashscope/deepseek-v4-flash` all returned `gemini-3-flash-preview` on full-size requests, and the
harness's model-identity guard stopped each run at the first slot. Only `vertex_ai/gemini-3.8-flash`
held its identity across a full run. The other two answerers therefore ran through OpenRouter, which
returned the requested identity on every slot. Without that guard this table would have compared one
model against itself three times.

## Reproduce

```bash
.bench-mps-venv/bin/python -m benchmarks.answer_contexts_v2 \
  --results docs/benchmarks-delivery-v3/results.json.gz

.bench-venv/bin/python -m benchmarks.answer_v2_report \
  docs/benchmarks-next/answer-v2-gemini-3.8-flash-checkpoint.json.gz \
  docs/benchmarks-next/answer-v2-claude-haiku-4.5-checkpoint.json.gz \
  docs/benchmarks-next/answer-v2-gpt-5-mini-checkpoint.json.gz
```

The report tool scores each attempt with `benchmarks.answer_experiment.score_answer`, unchanged from
round 1, and aggregates with the same per-attempt definitions as the frozen `answer_statistics`
summariser, which hardcodes the five round-1 arm names and therefore cannot accept this arm set.
