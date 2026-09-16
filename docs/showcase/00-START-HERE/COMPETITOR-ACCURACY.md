# Accuracy against everything else — every comparison this project has actually run

> **STATUS · CURRENT** — assembled 2026-09-14 from the documents named in each section · chain and
> replacements in [`VERSION-MAP.md`](VERSION-MAP.md)

One page, all angles. Nothing here is new measurement: every number is copied from a result document
in this folder and the source is named beside it, so any figure can be traced back in one step.

**Read the framing first, or the tables will over-claim.** Only one third-party system has been run
on the same corpus, the same questions, the same answerer and the same proxy as Chronoverse
(LightRAG). Graphiti was run on a different fixture and scores edges, not answers. Microsoft GraphRAG
has not been run at all. Long context is a baseline, not a product. The vendor tables at the end
compare *components* (embedding and rerank services), not systems.

| Comparison | Same corpus? | Same questions? | Same answerer? | Strength |
| --- | --- | --- | --- | --- |
| Chronoverse arms vs **LightRAG 1.5.7** | yes | yes (100) | yes | head-to-head, chunking caveat open |
| Chronoverse vs **long context** | yes (synthetic) | yes (150×3) | yes (3 models) | head-to-head |
| Chronoverse vs **Graphiti 0.30.2** | same fixture, different ingestion | yes (175) | n/a — edge scoring | indicative only |
| Chronoverse vs **Microsoft GraphRAG** | — | — | — | **not run** |
| Local vs **hosted embeddings / Cohere rerank** | public BEIR | yes | n/a | component-level |

---

## 1. Head-to-head on the licensed real corpus — the strongest comparison

Source: `01-results-open/ASOF-PILOT-RESULTS.md`, scoreboard regenerated in
`00-START-HERE/SIX-ARM-SCOREBOARD.txt`. 55 weekly market-price reports, 51 issues, 14 series,
100 questions sampled from 598 candidates (seed 20260913), answerer `vertex_ai/gemini-3.8-flash`,
temperature 0, top-k 8. Gold parsed mechanically from the price grid; no model judged any answer.

| System / arm | Correct | Gold in context | Answered from a later issue | Abstained | Context tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| **LightRAG 1.5.7 hybrid** (own graph + chunking) | **28.0%** | n/a | 1.0% | 47.0% | 33,026 |
| `static` — one index, no time awareness | 77.0% | 79.0% | 0% | 2.0% | 958 |
| `postfilt` — retrieve, then drop the future | 77.0% | 79.0% | 0% | 2.0% | 609 |
| `asof` — restrict to known issues, then retrieve | 90.0% | 92.0% | 0% | 0% | 959 |
| `static_item` — latest per series, whole corpus | 6.0% | 11.0% | 0% | 92.0% | 1,540 |
| **`asof_item`** — known issues, then latest per series | **100.0%** | 100.0% | 0% | 0% | 1,403 |

Exact McNemar, two-sided, paired: LightRAG loses **72 questions to `asof_item` and wins none**
(p < 0.0001); loses 62 to `asof`; and loses even to the plain time-unaware index, 53 to 4.

**Per series, LightRAG vs the best arm** (correct / n) — the loss is uniform, not one bad series:
13 HDPE film China 3 vs 13 · 11 LDPE film Vietnam 4 vs 11 · 10 HDPE injection >10 China 1 vs 10 ·
9 HDPE blow moulding Vietnam 0 vs 9 · 9 HDPE injection China 1 vs 9 · 9 LDPE film SE Asia 2 vs 9 ·
9 LLDPE film China 3 vs 9 · 9 LLDPE film SE Asia 3 vs 9 · 7 HDPE injection ≤10 China 3 vs 7 ·
5 HDPE blow moulding China 3 vs 5 · 5 LDPE film SE Asia all-origins 2 vs 5 · 4 LDPE film China 3 vs 4.

**How LightRAG fails matters.** It is not answering with future prices — only 1% of its answers take
a value from a later issue. It abstains on 47% of questions: given the date in the question text, it
cannot narrow to the issue that was current then, and 24× more context does not rescue it.

**Two caveats that travel with this table.** LightRAG brought its own chunking, so part of the gap is
chunking rather than time awareness — the clean rerun feeds it the same 970 assessment-row chunks and
is item 2 of the next round. And LightRAG is built for multi-hop questions over entity graphs; this
question form is a single-hop lookup with a date, which is the shape the projection is built for.

---

## 2. Against long context — the baseline that actually competes

Source: `01-results-open/ROUND2-ANSWER-RESULTS.md`. Synthetic delivery-clock fixture, arms A2/B/C2/
D/D2/E/Z, 4,096-token completion budget, three answerers. Arm **B** is long context (every version of
every item in the prompt); arm **E** is Chronoverse's delivery projection plus item view.

| Arm | System | Gemini 3.8 Flash | Claude Haiku 4.5 | GPT-5-mini |
| --- | --- | ---: | ---: | ---: |
| Z | no retrieval | 10.0% | 4.7% | 10.0% |
| D | global lifecycle + post-filter | 40.0% | 30.0% | 40.0% |
| A2 | RAG, lexical + dense | 59.0% | 54.0% | 54.0% |
| C2 | RAG + cross-encoder | 67.0% | 62.7% | 62.0% |
| D2 | delivery projection | 78.0% | 68.7% | 78.0% |
| **B** | **long context, every version** | **88.0%** | **78.7%** | 78.0% |
| **E** | **delivery + item view** | **88.0%** | **78.7%** | **88.7%** |

On closed-form accuracy **E ties long context on two answerers and separates only on GPT-5-mini
(+10.7)**. The separation is elsewhere:

| Measure, E minus B | Gemini 3.8 Flash | Claude Haiku 4.5 | GPT-5-mini |
| --- | ---: | ---: | ---: |
| End-to-end correctness | +1.1 | +8.1 | +75.5 |
| Stale citations (lower is better) | −1.0 | −6.7 | −82.0 |
| Tokens per answered question | −59% | −55% | −59% |

End-to-end: E scores 86.7 / 87.4 / 87.4% with **0% stale citations**, against B's 85.6 / 79.3 / 11.9%
with 1–82% stale. The claim this supports is citation hygiene and token cost at equal accuracy — not
"we beat long context".

---

## 3. Against Graphiti 0.30.2 — a different question, answered honestly

Source: `03-reviews-and-proposals/GRAPHITI-HEAD-TO-HEAD.md`. Native graphiti-core 0.30.2 on Neo4j
5.26.2, `google/gemini-2.5-flash` via OpenRouter, local MiniLM embedder, the 175 correction-family
TEST questions from the frozen `delivery-v3` fixture. $1.91, 716 s at concurrency 6.

| Family | n | Graphiti shared graph | Graphiti per-recipient `group_id` |
| --- | ---: | ---: | ---: |
| delayed_correction | 75 | 22 (29.3%) | **50 (66.7%)** |
| delayed_retraction | 50 | **41 (82.0%)** | 33 (66.0%) |
| historical_event_receipt | 50 | 33 (66.0%) | 34 (68.0%) |
| **total** | **175** | **96 (54.9%)** | **117 (66.9%)** |

Paired: per-recipient wins 55, shared wins 34, exact McNemar p = 0.033.

**The Chronoverse comparison on the same 175 cases is deterministic, not answer-scored**: bitemporal
rules alone give 0/175 for one shared graph and 175/175 for per-recipient partitions, and
Chronoverse's own store scores **174/175** because it retrieves ledger records directly and never
re-extracts them. Do not put 174/175 and 96/175 in the same sentence as if they were the same
measurement — the gap is dominated by Graphiti's LLM extraction channel, where roughly a third of
gold facts never survive extraction, entity resolution and hybrid search.

What it does establish: a delivery clock changes answers **inside** a third-party temporal graph, in
the predicted direction, on the family it was predicted for. Graphiti 0.30.2 has no recipient
dimension at all, and emulating one costs a graph partition per recipient — on this fixture a 20.8×
ingestion replication.

What it does not establish: that Chronoverse retrieves better than Graphiti.

---

## 4. Components, not systems — where vendor services beat the local stack

Sources: `01-results-open/HOSTED-RESULTS.md`, `OPENROUTER-RERANK-RESULTS.md`. Public BEIR corpora,
so these are shareable and reproducible outside the team.

| Retrieval, nDCG@10 ×100 | SciFact | NFCorpus | FiQA |
| --- | ---: | ---: | ---: |
| Strong BM25 | 66.47 | 32.54 | 23.61 |
| Local BGE at512 | 71.27 | 34.38 | 40.35 |
| Local three-way RRF at512 | 71.84 | 36.00 | 40.65 |
| **Hosted text-embedding-3-large** | **78.10** | **41.93** | **54.85** |

| Rerank, SciFact 300 queries | nDCG@10 | Recall@10 | Hit@1 |
| --- | ---: | ---: | ---: |
| Original RRF order | 67.34 | 81.51 | 53.33 |
| Local MiniLM cross-encoder | 68.86 | 82.56 | 56.33 |
| **Cohere rerank v3.5** | **77.37** | **87.69** | **66.67** |

Cohere beats the local cross-encoder by +8.51 points (Bonferroni 97.5% interval +5.39 to +11.76,
Holm p = 0.0001). Read this as "the retrieval floor is a bought component", which is also why the
as-of pilot's first index mattered more than its retrieval policy: chunking and ranking quality
dominate until they are fixed.

---

## 5. Where the clock loses — the negative result, kept in

Source: `01-results-open/03-benchmarks-longmemeval-README.md`. LongMemEval-S, all 500 public
question ledgers, local dense retrieval, frozen MiniLM protocol.

| Method | Session recall@5 | @10 | All support sessions@5 | @10 |
| --- | ---: | ---: | ---: | ---: |
| Dense | 79.82% | 90.01% | 65.11% | 81.28% |
| Dense + inclusive session-date cutoff | 75.22% | 84.48% | 60.00% | 74.26% |

A strict session-date cutoff **costs** recall here, and worst on temporal-reasoning questions
(72.19% → 55.58% at @5). This benchmark does not support a temporal-retrieval claim, and the
diagnosis is in the same document: support sessions can be timestamped after the question.

---

## 6. Cost, since accuracy alone flatters the heavy systems

| Run | Inference | Wall clock | Result |
| --- | --- | ---: | ---: |
| LightRAG, index + 100 answers | 1,012 LLM calls, 4.88M prompt + 1.20M completion | 65 min | 28.0% |
| `asof_item` + `static_item`, 200 answers | 53,170 prompt + 21,627 completion, no LLM at index time | 211 s | 100.0% / 6.0% |
| Graphiti native, 175 cases | LLM extraction per episode, $1.91 | 716 s | 66.9% best arm |

Roughly **two orders of magnitude more inference for a quarter of the accuracy** on this corpus —
the item arms' index needs embeddings only and makes no LLM calls at all.

---

## 7. What is not measured, and must not be implied

- **Microsoft GraphRAG** — never run. Heaviest indexing cost of the three; last in the queue.
- **Hosted Zep, LlamaIndex, Vectara, any commercial memory product** — never run.
- **LightRAG on the shared 970-chunk index** — until then, part of the 72-question gap is chunking.
- **Out-of-sample confirmation** — both item arms were written *after* the ten `asof` failures were
  read, and scored on the same 100 questions. A fresh draw with all arms fixed in advance is the
  first item in the next round. Until it lands, 100% is an in-sample figure.
- **Other question forms** — every question here is "as of D, most recent value for series S", the
  exact axis the item view collapses along. Ranges, comparisons and superseded-version questions are
  untested, so 100% means "retrieval was the whole bottleneck on this form", not general accuracy.
- **Correction recovery on real data** — the licensed corpus has no retroactive revisions (460
  agreements, 0 disagreements), so the delivery clock is still only exercised on the synthetic
  fixture.

## 8. If you quote one line

> On a licensed third-party corpus, given the date in the question, LightRAG 1.5.7 answers 28.0% of
> 100 as-of questions and loses 72 of them to a projection-first pipeline that wins none in return —
> at ~2% of the inference cost. Against long context on the synthetic fixture the accuracy is a tie;
> the separation is 0% stale citations and 55–59% fewer tokens.

Everything else on this page needs its caveat attached.
