# Chronoverse — independent review and proposed next round

> **STATUS · PROPOSAL** — original dated 2026-09-12 23:13 · chain and replacements in [`00-START-HERE/VERSION-MAP.md`](../00-START-HERE/VERSION-MAP.md) · a plan, not a result: check each WI against the status board before assuming it was done

**Reviewer:** external audit pass, 2026-09-12
**Scope reviewed:** `SCGC/Chronoverse` (rounds v1, v2, observer) and `SCGC/GraphRag+Chono` (research docs only, no executable benchmarks)
**Status of this document:** proposal for discussion. Nothing in the repository was modified during the review.

---

## 0. Headline

The measurement work is sound. Every published number reproduces. The problem is not honesty or rigor — it is **experimental design**: two of the three rounds were built so that the architecture could not win, and the third round contains a genuinely defensible result that is currently buried under a weaker headline.

The recommendation is therefore not "measure more carefully". It is: **keep the measurement discipline exactly as it is, and change what is being measured.**

---

## 1. Verification log — what was independently recomputed

All figures below were recomputed with scoring code written from the published protocol, not by calling the project's own scoring functions. Official BEIR qrels were read directly from `.benchmark-data/`.

| Claim | Source | Independent result |
| --- | --- | --- |
| v1 SciFact: BM25 / dense / RRF / Store nDCG@10 | `docs/benchmarks/scifact-*.run.json` | 0.6518 / 0.6115 / 0.6734 / 0.6920 — exact match, Recall@10 also exact |
| v2 cross-domain, 3 datasets × 6 systems | `cross-domain-results.json` | all 18 nDCG@10 values exact |
| v2 temporal, 4 systems × gated/ungated | `temporal-results.json` | micro P/R, 36/42 empty abstentions, 4/72 false abstentions — exact |
| Reranker gain +0.015268, CI [−0.0138, +0.0441] | `rerank-results.json` | +0.015268; own bootstrap (different seed, 20k samples) [−0.0144, +0.0443] — interval includes zero, as published |
| "300/300 top-10 identical to v1", nDCG 0.691969 | `index-results.json`, both optimization runs | verified across all four runs |
| Observer: leakage 24/50 and 62 items; 0 for all three receipt-aware methods | `docs/benchmarks-observer/results.json` | reconstructed receipt visibility from `fixture.json` independently — exact match |
| Observer: support 30/36, 29/36, 35/36; precision 0.3125 / 0.3061 / 0.4394 / 0.4730 | same | exact match under the published `support_units` definition |
| SQL control ≡ observer adapter | same | top-5 IDs, scores and candidate projections identical on all 50 queries |
| Dataset integrity | SciFact archive | MD5 equals the official BEIR MD5; 300 test queries / 339 qrel pairs / 5,183 docs = official split |
| Test counts "77 backend + 579 benchmark" | pytest collection | 77 and 579 collected |
| DEV/TEST leakage in temporal v2 | `temporal-v2.json` | entity overlap 0, scenario-family overlap 0; gate grid touches DEV only in code; qrels never reach any tuning path |

**Conclusion: the numbers are trustworthy.** Everything below is about what they mean.

---

## 2. What each round actually established

**Round 1 (SciFact + LightRAG).** Chronoverse scored +0.0186 nDCG over the RRF hybrid with a confidence interval that includes zero, using a benchmark-only unbounded document cache. Correctly reported as inconclusive. The LightRAG comparison is real library execution with an LLM trap, correctly caveated as a supplied-KG adaptation rather than an end-to-end LightRAG benchmark.

**Round 2 (production index + cross-domain + reranker + temporal v2).** Strong systems work: persisted vectors, 300/300 ranking preservation, warm p50 from 1.572 s to 0.800 s with identical output. The retrieval-model comparison is clean and the honest reporting of "BM25 + BGE is *worse* than BGE alone on FiQA" is the kind of result that builds credibility.

**Round 3 (observer receipts).** First round that produces real separation: out-of-scope context 48% → 0%, correct abstention on empty-support questions 11% → 56%.

---

## 3. The structural problem in rounds 1–2

Three design decisions made a positive result unreachable:

1. **The baselines are handed the architecture for free.** `BM25 + reference scope/evidence` is the temporal semantics, implemented for the competitor. A tie is then guaranteed by construction, and the artifacts show exactly that: `Chronoverse actual Store` and `Dense + reference scope/evidence` are *identical in every gated and ungated cell* of the round-2 temporal table.
2. **Ceiling effect.** Ungated micro recall is 1.0000 for all four systems. With an average visible pool of 72 candidates and roughly 0.7 gold items per question, every system finds everything within the top 10. There is no headroom in which to differentiate.
3. **The metric cannot see the value.** nDCG rewards ranking. The claimed benefit of a time axis is *answering with the correct version of a fact*, and *never using evidence the answerer could not have had*. Neither is visible in nDCG.

This is why round 3 matters: it is the first fixture whose primary metric (leakage, abstention) is capable of separating the systems.

---

## 4. The one claim that is genuinely defensible today

Not the adapter. **Filter order.**

| Configuration | Support units recovered |
| --- | ---: |
| Receipt filter applied *after* lifecycle projection | 29 / 36 |
| Receipt filter applied *before* projection (SQL control) | 35 / 36 |
| Receipt projection inside the Store (adapter) | 35 / 36 |

The gap is exactly six queries, and they were isolated case by case:

| Query | Family | Post-projection filter | Pre-projection filter |
| --- | --- | --- | --- |
| `oq10` | delayed_correction | ∅ | `cx9r` |
| `oq16` | delayed_retraction | ∅ | `er5n` |
| `oq18` | delayed_retraction | ∅ | `er5n` |
| `oq14` | delayed_correction | `dq2v` only | `cx9r` + `dq2v` |
| `oq48` | delayed_correction | `dq2v` only | `cx9r` + `dq2v` |
| `oq43` | historical_event_receipt | `wx2e` only | `vw9a` + `wx2e` |

Every one is a delayed correction, retraction, or late lifecycle receipt. The generalizable statement is:

> A system without temporal projection *inside* retrieval cannot recover these cases by filtering its output afterwards. The older claim has already been retired by an event the recipient has not yet received, so it is absent before the filter ever runs. Filtering removes; it cannot restore.

This holds regardless of embedding model, ranker, reranker, or context window size. It is model-independent, falsifiable, and it survives the SQL control — because the SQL control also filters *before* projection. The control confirms the claim rather than defeating it.

**Action: make filter order the headline of the round-3 write-up, not the observer adapter.**

---

## 5. Positioning and naming

### 5.1 The third clock

The contribution is best stated as **tri-temporal retrieval**:

| Clock | Question it answers |
| --- | --- |
| `valid_at` | when was this true in the world |
| `known_at` | when did the ledger learn it |
| `received_at` | when did *this particular recipient* receive it |

Standard bitemporal database literature (valid time + transaction time) is well established and is not novel. The per-recipient delivery clock, applied *before* lifecycle projection, with correction and retraction notices that themselves have delivery times, is the part that is thin in the literature. That is where a claim should be staked.

### 5.2 On the quantum / "subjective reduction" framing

Regarding the observer-dependent collapse and subjective-reduction framing raised in the last round: the historical terminology is real — von Neumann's projection postulate, Wigner's consciousness-causes-collapse reading, and the "subjective reduction" label attached to it — but attaching it to this system is a net negative, for three reasons.

1. **It is factually the wrong mechanism.** Nothing here is probabilistic, nothing is superposed, no measurement disturbs a state, and no outcome depends on a conscious subject. What the experiment implements is an access-control join over a delivery log. The project's own SQL control proves this: an ordinary SQL query reproduces every payload and every score exactly. If a classical relational query is a perfect substitute, the phenomenon is classical by definition.
2. **It inverts the direction of the analogy.** In collapse interpretations, observation *changes* the system. Here, the ledger is append-only and immutable — observation changes nothing at all. Only the *view* differs per recipient, which is ordinary perspectival bookkeeping, closer to relational database views or to epistemic logic (what agent A knows at time t) than to physics.
3. **It costs credibility exactly where the work is strongest.** The measurement discipline in this project is unusually good — frozen fixtures, hash-pinned sources, published counterevidence, intervals that include zero. Any reviewer who sees a quantum framing will discount that discipline before reading the tables. The existing documents already handle this correctly ("This is a classical software experiment, not a model of physical wavefunction collapse"). Keep that line, and go further: remove the framing from titles and directory names too.

If a conceptual vocabulary beyond databases is wanted, the defensible neighbours are **epistemic / doxastic logic** (agent-indexed knowledge operators over time) and **relational or perspectival information models** — used explicitly as an analogy, never as a mechanism.

**Action: rename the track from "observer" to "recipient delivery time" or "tri-temporal". Keep the physics vocabulary out of artifact names, headings, and abstracts.**

---

## 6. Engineering debt to clear before the next round

### 6.1 Version control (highest priority, lowest effort)

Neither `Chronoverse/` nor `GraphRag+Chono/` is a git repository. Consequences:

- "No parameters were tuned against test labels" is currently unverifiable. The ranking constants (`0.35 × lexical + 0.50 × vector + 0.15 × graph`, cosine gate `0.28`) are hardcoded with no history showing they predate the benchmarks.
- "Predeclared" and "frozen before test scoring" rest on file mtimes, which any process can rewrite.
- Rollback of an experiment that changes production code depends on manual `source/` copies.

Fix: `git init` both folders; commit the application constants and the fixture *before* each run; record the commit SHA next to the existing source SHA-256 in every result JSON. This costs an hour and converts several claims from self-reported to auditable.

### 6.2 Wording of "independent"

`verify_v2_artifacts.py` and `verify_observer_experiment.py` live in the same repository and share authorship with the code under test. They are valuable second implementations, but "independent audit" and "independent reviewer" overstate it. Suggested wording: *"a second implementation in this repository recomputed every aggregate from the raw artifacts"*. Reserve "independent" for code written outside the project — this review is an instance, and its results can be cited as such.

### 6.3 Baseline fairness

Two gaps that a reviewer will find immediately:

- **BM25 is under-strength.** `rank_bm25.BM25Okapi` at library defaults (k1=1.5, b=0.75), no stemming, no stopword removal, single concatenated field. Published tuned BM25 on the same splits reaches roughly 0.673 / 0.313 / 0.244 (SciFact / NFCorpus / FiQA) against this project's 0.6519 / 0.3064 / 0.2167. The FiQA gap is about 11% relative — and FiQA is exactly where the paper-worthy claim "adding BM25 hurts" is made. Fix with Pyserini/Anserini or Elasticsearch at BEIR defaults (k1=0.9, b=0.4, stemming, stopwords, title + text fields), then rerun the hybrids.
- **Truncation asymmetry.** MiniLM truncates at 256 tokens, BGE at 512. Part of the measured "BGE > MiniLM" is context length, not model quality. It is disclosed inside the result JSON but not next to the table. Fix by running both at a common `max_seq_length`, and optionally BGE at both lengths to quantify the effect.

### 6.4 Performance work — what to do and what to defer

The persisted-vector work is correct and the ordering of concerns is right. Recommended continuation:

- Keep exact scoring as the correctness reference. Do not adopt ANN until candidate scoring is a measured bottleneck at a corpus size the product actually has; when that happens, measure recall lost against the exact fallback rather than assuming it is negligible.
- The projected next costs (lexical tokenization, projection) are already identified by profiling — continue there.
- Timing comparisons across runs on a shared machine cannot support causal speedup claims; the documents already say this. Keep timings as observations and let the exact output-equality checks carry the weight.
- For the versioned-vector design sketched in `NEXT-ARCHITECTURE.md`: half-open knowledge intervals per text version is the right shape. Add the delivery clock to that design now rather than later — a `received_at` dimension retro-fitted onto a two-clock index is a painful migration.
- Redis remains unnecessary for a single-process local deployment. Revisit only when multi-worker sharing is measured.

---

## 7. Proposed experiment programme

### E0 — Fair-fight repairs (no API, ~1 day)

Pyserini BM25 at BEIR defaults; equal `max_seq_length`; `git init` + commit SHA in every result file. Rerun round-2 cross-domain unchanged otherwise. Expected outcome: some hybrid conclusions move; the "BM25 hurts on FiQA" claim either survives against a strong BM25 or is retracted. Either way the result becomes defensible.

### E1 — Scale the round-3 fixture until it stops saturating (no API, ~2 days)

Round 3 is the right experiment at the wrong size. Extend it rather than replacing it:

- 50 → 500 questions, with distractor corpus of 5,000+ assertions so top-k is not trivially satisfied.
- Keep the proportion of `delayed_correction`, `delayed_retraction` and `historical_event_receipt` high — those are the families that separate systems.
- Add near-duplicate assertions that differ **only** in time coordinates, so lexical and dense similarity cannot break the tie and only the temporal projection can.
- **Change the primary metric** to *recovery rate on correction-sensitive cases*. Today the six decisive queries are diluted into an aggregate (6/36) and the headline reads as a 17% difference; reported on their own family the effect is 6/6 versus 0/6.
- Report leakage, recovery, and precision separately. Do not average them.

Secondary fix: questions whose gold is a lifecycle event only are currently scored as "must abstain". The rule is applied uniformly so no bias results, but returning a correction notice arguably *is* the correct answer. Split that family out and score it on its own terms.

### E2 — End-to-end answer quality (paid API, ~2 days) — the decisive test

Identical answerer, identical prompt, identical context budget, temperature 0. Only the retrieval layer changes:

| Arm | Retrieval |
| --- | --- |
| A | Vanilla RAG over chunks with dates written in the prose |
| B | Long context — every version of every fact, plus "today is {date}" in the prompt |
| C | Vanilla RAG + cross-encoder reranker |
| D | Vanilla RAG + post-hoc metadata filter (the strong classical control) |
| E | Chronoverse tri-temporal projection |

Metrics, in priority order:

1. **Stale-version rate** — answered with a fact superseded at `valid_at`.
2. **Delivery leak rate** — answered using evidence the recipient had not received at `received_at`.
3. **Correction recovery** — the E1 families, at answer level.
4. Answer exact match, and correct abstention.

Arms B and D are the ones that matter. If B (a large model with the entire history in context) matches E, the retrieval architecture is not carrying the claim and the team should know that. If D matches E, filter order does not matter at answer level and section 4 is weakened. The experiment is designed so that it can lose.

### E3 — Public data (paid API, ~2 days)

Removes the "gold authored by the same team" objection:

- **StreamingQA** — 147k questions explicitly about adaptation to knowledge arriving over time. Closest public proxy for `known_at`.
- **ChronoQA** — 5,176 questions over 300k news articles 2019–2024, CC BY 4.0, Zenodo DOI `10.5281/zenodo.17163857`. Chinese, which also tests the non-English gap the round-2 docs flag.
- **ArchivalQA / ChroniclingAmericaQA** — large timestamped document corpora.
- **MultiTQ / MusTQ** — multi-hop, but valid-time only; useful for the graph ablation, not for the delivery clock.

No public benchmark covers late correction with per-recipient delivery. That gap is the argument for keeping a synthetic fixture — but it must be authored differently: write the semantics as a prose specification, then have a separate agent that has never read `store.py` implement the reference and author the gold from that specification alone. Today the gold and the reference policy share an author with the implementation, which is a stronger form of circularity than "synthetic".

### E4 — Ablation (paid API, ~1 day)

Same retriever, same model, same budget; remove one clock at a time: full tri-temporal / valid+known / valid only / none. This produces the sentence the theory actually needs: *"removing the delivery clock causes X% of answers to use evidence the recipient did not have."*

---

## 8. Budget

Current published rates: Claude Haiku 4.5 $1/$5 per MTok · Sonnet 5 $2/$10 · Opus 5 $5/$25 · **Batch API −50%** · Voyage embeddings $0.12/MTok.

E2 at full size — 500 questions × 5 arms = 2,500 calls at roughly 3k input / 300 output tokens:

| Item | Estimate |
| --- | ---: |
| Answerer, Haiku 4.5 via Batch | ≈ $5 |
| Answerer, Sonnet 5 via Batch (if a stronger answerer is wanted) | ≈ $9 |
| Judge, Opus 5 via Batch | ≈ $8 |
| Hosted embeddings, 3 corpora ≈ 10M tokens | ≈ $1.20 |
| **Whole programme, 3 seeds, headroom included** | **≤ $50** |

Cost is not the constraint. Gold authoring is. Spend the API budget on *paraphrases, distractors and plausible-but-wrong evidence* — never on generating gold answers, which would reintroduce the circularity E3 is meant to remove. Run everything through the Batch API; none of this is latency-sensitive.

---

## 9. Statistical protocol

- Write `PREDICTIONS.md` before any run: what is expected to win, **and what is expected to lose**. Commit it, publish the hash. The round-2 documents already do something close to this; make it formal.
- Multiple comparisons: rounds 1–2 compare 6 systems across 3 datasets with no correction, correctly disclosed. Apply Holm, or label every comparison exploratory.
- Power: at least 300 questions per arm for a ±0.03 effect to be resolvable.
- Keep the paired bootstrap; keep publishing intervals that include zero.

---

## 10. Kill criteria

State these before running, and honour them:

- If arm B (long context, full history) matches arm E on stale-version and delivery-leak rate, the architecture's advantage is a cost/latency argument, not a correctness argument. Say so.
- If arm D (post-hoc metadata filter) matches arm E on correction recovery at answer level, section 4 does not generalize beyond retrieval, and the headline reverts to engineering.
- If a strong Pyserini BM25 erases the round-2 hybrid conclusions, retract them in place rather than re-running until they return.

A programme with published kill criteria that survives them is worth far more than one that always wins.

---

## 11. What to claim, and what not to

**Claimable now.** Immutable assertion/event ledger with tri-temporal projection; exact output preservation across four production optimization stages; a model-independent correctness result about filter order on late corrections; an unusually complete reproduction package.

**Not claimable now.** Superiority over GraphRAG systems. A unique graph-reasoning advantage. Any quantum, collapse, consciousness or subjective-reduction mechanism. Retrieval-quality improvements attributable to temporal semantics — the current evidence says a filtered conventional retriever ties, and that finding is already published, which is to the team's credit.

**Reachable in one round.** A falsifiable, answer-level, publicly-grounded result that removing the delivery clock produces measurably wrong answers that no post-hoc filter and no long-context prompt recovers.

---

## 12. Sequence

| Day | Work | Cost |
| --- | --- | ---: |
| 0 | E0 — BM25, truncation parity, `git init`, commit SHAs in results | $0 |
| 1–2 | E1 — scale round-3 fixture, new primary metric | $0 |
| 3 | E2 pilot, 50 questions, validate the harness | ≈ $1 |
| 4–5 | E2 full, 5 arms, 3 seeds | ≈ $15 |
| 6 | E4 ablation | ≈ $8 |
| 7 | Report, kill-criteria review, rename the track | $0 |

E0 and E1 need no API key and can start immediately.

---

## Appendix — review method

Read-only. No project file was created, modified, or deleted. Metrics were recomputed with scoring code written from the published protocols; BEIR qrels were read from `.benchmark-data/`; the observer receipt visibility model was reconstructed from `fixture.json` rather than from the adapter. Test counts were obtained by pytest collection with `-p no:cacheprovider`. External reference values for BM25 come from published BEIR evaluations.

---

## 13. Prior art and where this sits

A literature scan was run after the review. Summary: **the two-clock part is taken; the third clock is not.**

### 13.1 Already published — do not claim novelty here

**Bitemporal retrieval for agent memory is commercial, published and benchmarked.** Zep's Graphiti (arXiv 2501.13956) is a temporal knowledge-graph engine for agent memory that tracks exactly two clocks per edge — valid time (when the fact was true) and transaction/ingestion time (when the system learned it) — supports point-in-time "what was true on this date" queries, marks contradicted facts invalid instead of deleting them so history is preserved, and traces every fact to the source episode that produced it. It reports 94.8% vs 93.4% against MemGPT on Deep Memory Retrieval and up to +18.5% accuracy on LongMemEval with roughly 90% lower latency.

That is, feature for feature, the valid-time + known-time half of Chronoverse — with published benchmark numbers attached. Bitemporal modelling itself is older still, standard database literature. **Any positioning that leads with "we track valid time and knowledge time" will be read as a reimplementation of a shipped product.**

Adjacent work that also overlaps: temporal GraphRAG variants that resolve conflicting facts over time (T-GRAG), modular time-sensitive RAG (MRAG), and permission- or security-filtered RAG, which applies per-caller access control to retrieval — static ACLs rather than a delivery clock, but the same shape of idea.

### 13.2 What appears genuinely open

1. **A per-recipient delivery clock as a retrieval dimension.** Graphiti records which episode *produced* a fact; nothing found records which recipient *received* it, or filters retrieval by that. Access-control RAG filters by static permission, not by time of arrival, and cannot express "Red had the original report but not yet its correction".
2. **Filter order as a correctness property.** The finding in §4 — that a post-hoc filter cannot recover a claim already retired by an unreceived correction — was not found stated or measured anywhere. It is small, precise, model-independent and falsifiable, which is exactly the profile of a publishable systems result.
3. **Delivery-aware lifecycle events.** Corrections and retractions that themselves have per-recipient arrival times, so a recipient can hold a claim its correction has not yet reached. This is the mechanism behind both points above.

### 13.3 Public benchmarks that fit the third clock

The "we wrote our own gold" objection can be retired without waiting for a new dataset:

- **FANToM** (EMNLP 2023, [project page](https://hyunw.kim/fantom/), [code and data](https://github.com/skywalker023/fantom)) is the closest public match found. Multi-party conversations in which characters join and leave, so participants miss information that is shared in their absence — *natural information asymmetry created by arrival and departure times*. Its question types are BeliefQ, AnswerabilityQ and InfoAccessQ: who is aware of what. This is the delivery clock, authored independently, in public, with a license. Adapting it is direct: treat presence intervals as receipts, build the ledger from the conversation, then answer InfoAccessQ and AnswerabilityQ through retrieval instead of prompting. A win here is worth more than any number of in-house fixture points.
- **LongMemEval** (ICLR 2025) — 500 questions, 30–40 sessions (~115k tokens) or ~500 sessions (~1.5M tokens), testing information extraction, multi-session reasoning, **knowledge updates**, **temporal reasoning** and **abstention**. This is the arena where Zep published its numbers, so it is the natural head-to-head. Knowledge updates and abstention map onto correction handling and empty-support behaviour, which round 3 already measures.
- **StreamingQA**, **ChronoQA**, **ArchivalQA** as before for knowledge-time and timestamped corpora.

### 13.4 Assessment of potential

| Dimension | Reading |
| --- | --- |
| Novelty of the two-clock core | Low — prior art, commercial and academic |
| Novelty of the delivery clock + filter-order result | Moderate and defensible, if measured at answer level on public data |
| Evidence currently in hand | Strong method, weak statement of claim; 6 decisive cases in a 50-question synthetic fixture |
| Fastest credibility gain | FANToM adaptation, then LongMemEval head-to-head against a Graphiti baseline |
| Publication realism | Workshop or systems-track paper if E1+E2 land, framed as *delivery-time-aware retrieval*, never as anything quantum |
| Product realism | Strongest where "who knew what, when" is a compliance requirement: regulated communications, insider-information boundaries, incident timelines and audit replay, multi-tenant agent fleets where one agent must not answer from another's inbox |
| Main risk | A long-context model with the full history and an explicit "as of" instruction may match the architecture on answer accuracy. E2 arm B is designed to detect exactly this. |

Recommended one-line positioning for the next round:

> Retrieval that is correct for *a particular recipient at a particular moment*, including facts whose corrections have not yet reached them — and a measurement showing that filtering a conventional system's output afterwards cannot reproduce it.

Sources: [Zep / Graphiti (arXiv 2501.13956)](https://arxiv.org/abs/2501.13956) · [Graphiti temporal model](https://www.getzep.com/ai-agents/temporal-knowledge-graph/) · [FANToM](https://hyunw.kim/fantom/) · [LongMemEval](https://xiaowu0162.github.io/long-mem-eval/) · [Temporal QA survey](https://arxiv.org/html/2505.20243) · [ChronoQA](https://www.nature.com/articles/s41597-025-06098-y) · [T-GRAG](https://pith.science/paper/2508.01680) · [Secure Multifaceted-RAG](https://www.mdpi.com/2078-2489/16/9/804) · [BEIR BM25 reference numbers](https://blog.vespa.ai/improving-zero-shot-ranking-with-vespa-part-two/) · [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing)

---
---

# Part II — Execution specification

Part I is the argument. Part II is the work. Each item below is written so that an agent or engineer can pick it up without re-deriving the reasoning: goal, why it exists, concrete steps, and an acceptance test that either passes or fails.

Conventions used throughout:

- Paths are relative to `SCGC/Chronoverse/` unless stated otherwise.
- Existing environments are reused: `.bench-venv` (CPU/fastembed experiments), `.bench-mps-venv` (torch/MPS experiments), `backend/.venv` (application).
- "Result JSON" means any file written under `docs/benchmarks*/`.
- No work item may change application ranking weights, thresholds, or the default model. If an item appears to require it, stop and raise it — that is a separate decision with its own experiment.
- Every item is independently revertible. Nothing here requires a rewrite of an existing round.

Effort markers: **S** ≈ under half a day · **M** ≈ one day · **L** ≈ two to three days.

---

## Track A — Provenance and repository hygiene (no API, do first)

### WI-01 — Put both folders under version control · S · blocks everything in Track C and E

**Why.** Three published claims currently rest on file modification times: "no parameters were tuned against test labels", "predeclared", and "frozen before test scoring". Modification times are not evidence. This is the cheapest credibility gain available.

**Steps.**

1. `git init` in `SCGC/Chronoverse/` and in `SCGC/GraphRag+Chono/`.
2. Add a `.gitignore` covering `.bench-*venv/`, `.tools-venv/`, `.model-cache/`, `.benchmark-data/`, `.runtime/`, `__pycache__/`, `.pytest_cache/`, `data/*.sqlite3*`, and `*.npy`. Result JSON and report HTML **are** committed; downloaded corpora and model weights are not.
3. First commit must include, unchanged, the current application constants — `backend/chronoverse/store.py` (the `0.35 / 0.50 / 0.15` weights and the `0.28` cosine gate), `semantic.py`, `lexical_index.py`, `vector_index.py`, `models.py` — and all existing fixtures under `benchmarks/data/`.
4. Tag it: `git tag round-3-as-published`.
5. Large existing artifacts: if `cross-domain-results.json` (19 MB) makes the repo unpleasant, either enable Git LFS for `docs/benchmarks*/**.json` over 5 MB, or commit a `*.json.zst` and keep the raw file ignored. Decide once and write the choice into `docs/README.md`.

**Acceptance.** `git log --oneline` shows the tagged commit; `git status` is clean after a full benchmark run except for intended result files; the weights file appears in the first commit's tree.

### WI-02 — One provenance block in every result file · S · depends on WI-01

**Why.** Result JSONs already carry source SHA-256 and package freezes, which is good. Adding the commit makes every number traceable to an exact tree state, and the dirty flag makes "we ran this with uncommitted edits" impossible to hide by accident.

**Steps.**

1. Add `benchmarks/provenance.py` with a single function returning a dict:

```python
def run_provenance() -> dict:
    """Identical block embedded in every result file."""
    return {
        "git_commit": ...,            # git rev-parse HEAD
        "git_dirty": ...,             # bool: git status --porcelain non-empty
        "git_describe": ...,          # nearest tag, for human reading
        "python": platform.python_version(),
        "platform": platform.platform(),
        "started_at": ...,            # ISO-8601 UTC
        "load_average": os.getloadavg(),   # machine contention at start
        "requirements_sha256": ...,   # hash of the frozen requirements file in use
        "source_sha256": {...},       # existing per-file hashes, unchanged
    }
```

2. Call it from every runner: `index_scifact.py`, `optimize_index.py`, `lexical_optimize_index.py`, `cross_domain.py`, `rerank_v2.py`, `temporal_v2.py`, `observer_experiment.py`, and every new runner in Tracks C–E.
3. Make the runners **refuse to write a result file when `git_dirty` is true**, unless `--allow-dirty` is passed explicitly, in which case the flag is recorded in the file.

**Acceptance.** Every file under `docs/benchmarks*/` written after this item contains a `provenance` object with a non-empty `git_commit`; a deliberately dirty tree refuses to produce a result file without the flag.

### WI-03 — Correct the word "independent" · S

**Why.** `verify_v2_artifacts.py` and `verify_observer_experiment.py` share a repository and an author with the code they check. They are genuinely useful second implementations, but the current wording ("independent audit", "independent reviewer") is the one place in the documentation where a reader can accuse the project of overstating.

**Steps.**

1. Replace "independent audit/auditor/reviewer" with "second implementation in this repository" in `docs/benchmarks-v2/README.md`, `VERIFICATION.md`, `docs/benchmarks-observer/README.md`, `VERIFICATION.md`.
2. Add `docs/EXTERNAL-REVIEW.md` summarizing the external recomputation recorded in Part I §1 of this document, with its date and its method (scoring code written from the protocol, BEIR qrels read directly, receipt visibility rebuilt from the fixture).
3. Where a figure has been externally reproduced, it is now legitimate to write "externally reproduced" — use it sparingly and only for the figures listed in §1.

**Acceptance.** No occurrence of "independent" applied to in-repo verification code; `EXTERNAL-REVIEW.md` exists and is linked from both round READMEs.

### WI-04 — Rename the third track and remove physics vocabulary · S

**Why.** Part I §5. The mechanism is classical; the project's own SQL control proves it. The naming is the only thing inviting a dismissal that the content does not deserve.

**Steps.**

1. Directory `docs/benchmarks-observer/` → `docs/benchmarks-delivery/`. Leave a `docs/benchmarks-observer/index.html` containing a one-line meta-refresh to the new path so existing links and the round-3 screenshots stay valid.
2. Code: `benchmarks/observer_experiment.py` → `delivery_experiment.py`, `observer_projection.py` → `delivery_projection.py`, `observer_fixture.py` → `delivery_fixture.py`, `verify_observer_experiment.py` → `verify_delivery_experiment.py`, `render_observer_report.py` → `render_delivery_report.py`. Tests follow the same rename.
3. Vocabulary inside the code and documents: `observer_id` → `recipient_id`, `observer_at` → `received_by`, `ObserverStore` → `DeliveryStore`, `SQLReceiptStore` unchanged. Keep `received_at` on receipts as-is; it is already the right word.
4. Documents: remove "observer" from headings and the abstract. The existing disclaimer sentence ("This is a classical software experiment, not a model of physical wavefunction collapse") can then be deleted rather than defended — once nothing in the naming suggests otherwise, the disclaimer draws attention to a claim nobody made.
5. If a conceptual framing is wanted in the write-up, use epistemic logic ("what recipient *r* knows at time *t*") or database views. Do not use collapse, measurement, observer effect, subjective reduction, or consciousness anywhere in titles, file names, or abstracts.

**Acceptance.** `grep -ril "observer\|collapse\|quantum\|subjective reduction" docs/ benchmarks/ backend/` returns only the redirect stub and a single historical note in a changelog, if any. All tests pass after the rename.

### WI-05 — One command that verifies everything · S

**Why.** Three rounds now have separate verification entry points. A single target makes "is the repository currently self-consistent" a one-line question, and is the hook a CI runner will eventually use.

**Steps.**

1. Add to `Makefile`:

```make
verify:
	backend/.venv/bin/python -m pytest backend/tests -q
	.bench-venv/bin/python -m pytest benchmarks/tests benchmarks/test_temporal_fixture.py -q
	.bench-venv/bin/python -m pytest benchmarks/test_delivery_projection.py benchmarks/test_delivery_review.py -q
	.bench-venv/bin/python -m benchmarks.verify_v2_artifacts
	.bench-venv/bin/python -m benchmarks.verify_delivery_experiment
```

2. Each verifier must exit non-zero on failure — check this by temporarily corrupting one number in a copy of a result file and confirming the failure.

**Acceptance.** `make verify` passes on a clean tree and fails loudly when a result file is perturbed.

---

## Track B — Make the baselines strong (no API)

### WI-06 — Replace the BM25 implementation · M · blocks WI-08

**Why.** Part I §6.3. The current baseline uses `rank_bm25.BM25Okapi` at library defaults with no stemming, no stopword removal, and a single concatenated field. Published tuned BM25 on these splits reaches roughly 0.673 / 0.313 / 0.244 (SciFact / NFCorpus / FiQA) against the project's 0.6519 / 0.3064 / 0.2167. The FiQA gap is about 11% relative, and FiQA is exactly where the round-2 claim "adding BM25 does not always help" is made.

**Steps.**

1. Add Pyserini (Anserini/Lucene) to a new isolated environment `.bench-lexical-venv`. If the JVM dependency is unacceptable on this machine, the alternative is a local Elasticsearch or OpenSearch container; the parameters below are what matter, not the engine.
2. Index each corpus with BEIR's standard configuration: BM25 `k1=0.9`, `b=0.4`, Porter stemming, English stopword list, and **two fields** — title and text — rather than one concatenated string.
3. Keep the existing `rank_bm25` run as a second, clearly labelled configuration. Report both. The weak configuration is not deleted; it becomes evidence about tokenization sensitivity.
4. Record in the result JSON: engine, version, analyzer, `k1`, `b`, field weights, and whether stopwords/stemming were applied.

**Acceptance.** SciFact BM25 nDCG@10 ≥ 0.660 and FiQA ≥ 0.235 with the tuned configuration. If either falls short, the harness is misconfigured — do not proceed to WI-08 until it does.

### WI-07 — Equalize dense model input length · S · blocks WI-08

**Why.** MiniLM truncates at 256 tokens, BGE at 512. Part of the measured "BGE beats MiniLM" is context length rather than model quality. This is disclosed inside the result JSON but not beside the table, and a reviewer will treat that as a confound.

**Steps.**

1. Parameterize `max_seq_length` in `benchmarks/cross_domain.py` (`get_embedder`) instead of accepting the model default.
2. Run four cells per dataset: MiniLM@256, MiniLM@512 (note that MiniLM's positional limit is 512 but it was trained at 256 — record what the runtime actually does rather than assuming), BGE@256, BGE@512.
3. Report the matched-length comparison as the headline and the mismatched one as a supplementary row.
4. Record the effective truncation statistics: percentage of documents in each corpus that exceed each limit. FiQA and NFCorpus will differ substantially from SciFact here, and that number is itself a useful finding.

**Acceptance.** The README table states the sequence length used for every dense row, and a supplementary table shows the BGE@256 vs BGE@512 delta per dataset.

### WI-08 — Re-run cross-domain and revisit the hybrid conclusion · M · depends on WI-06, WI-07

**Why.** The one genuinely comparative claim in round 2 — that adding BM25 to BGE *hurts* on FiQA (0.4035 → 0.3292) — was measured against an under-strength BM25. It may survive; it may not. Either outcome is publishable, and retracting it voluntarily is worth more than defending it.

**Steps.**

1. Re-run all six systems on all three datasets with the tuned BM25 and matched sequence lengths. Everything else — RRF `k=60`, top-100 candidate pools, linear-gain nDCG, bootstrap seed — stays exactly as it is.
2. Recompute the paired bootstrap against the same predeclared reference (`minilm_hybrid_rrf`), and this time apply a Holm correction across the comparison family (see WI-12).
3. Update `docs/benchmarks-v2/README.md` in place with both configurations side by side, and add one sentence saying which conclusions changed and which held.

**Acceptance.** All 18 (or 36, with both BM25 configurations) metrics reproduce through `verify_v2_artifacts.py`; the README explicitly states the status of the FiQA hybrid claim under a strong BM25.

---

## Track C — Temporal fixture v3, built so that systems can separate (no API)

### WI-09 — Scale the delivery fixture · L · depends on WI-01

**Why.** Round 3 is the right experiment at the wrong size: 50 questions, 18 assertions, 3 lifecycle events. Six queries decide the outcome. Round 2's fixture saturated (every system reached micro recall 1.0000); round 3's is small enough that a single authoring choice moves a headline percentage point by two.

**Target shape.**

| Quantity | Round 3 | v3 target |
| --- | ---: | ---: |
| Questions | 50 | 500 |
| Assertions | 18 | 5,000+ (distractors included) |
| Lifecycle events | 3 | 300+ |
| Receipts | 48 | ≥ 10,000 |
| Recipients | 2 | 8–12 |
| Distinct scenario families | ~6 | ≥ 12, DEV/TEST disjoint |

**Family proportions.** These are the families that separate systems; weight them accordingly rather than uniformly.

| Family | Share | What it tests |
| --- | ---: | --- |
| `delayed_correction` | 15% | recipient holds original; correction not yet delivered |
| `delayed_retraction` | 10% | claim retracted in ledger, retraction undelivered |
| `correction_before_replacement` | 10% | retraction arrives before the replacement claim; no active support exists at that instant |
| `historical_event_receipt` | 10% | lifecycle notice delivered late, question asks about the earlier view |
| `time_only_near_duplicate` | 15% | two assertions with **identical text**, differing only in `valid_from` / `valid_to`; lexical and dense scores tie by construction, so only projection can choose |
| `orphan_evidence` | 5% | evidence passage delivered without its parent assertion (the `oq41` case that the assertion-centric retriever misses) |
| `boundary_exact` | 10% | receipt, recording and validity boundaries at exactly equal timestamps, microsecond resolution |
| `cross_recipient_isolation` | 10% | same question, different recipients, different correct answers |
| `no_support` | 15% | correct behaviour is abstention |

**Distractor design.** Distractors must be semantically adjacent, not random: same entities, same predicates, neighbouring time windows. A distractor that any dense retriever rejects on topic alone contributes nothing.

**Steps.**

1. Extend `benchmarks/delivery_fixture.py` (renamed in WI-04) into a generator with an explicit seed, an entity pool split DEV/TEST, and the family table above as data rather than code.
2. Preserve the existing freeze behaviour: the runner already refuses to overwrite a differing fixture, which is correct — keep it and extend it to record the generator's own SHA-256 and seed.
3. DEV/TEST split by **entity and by family**, as round 2 did (verified: zero overlap on both axes). Any calibration happens on DEV only.
4. Keep every round-3 question in the v3 fixture as a labelled subset so the two rounds remain comparable.

**Acceptance.** 500 unique recipient/query/scope combinations; zero DEV/TEST entity or family overlap; regenerating with the same seed reproduces the fixture hash exactly; the six round-3 decisive queries are still present and still behave as recorded.

### WI-10 — Fix what the metrics report · M · depends on WI-09

**Why.** The decisive evidence in round 3 is currently diluted. Six queries out of 36 support units reads as a 17% difference; reported on its own family it is 6 of 6 against 0 of 6. Aggregates hide the effect that matters.

**Steps.**

1. Change the primary reported metric to **recovery rate on correction-sensitive families**, defined as: of the gold support units belonging to `delayed_correction`, `delayed_retraction`, `correction_before_replacement` and `historical_event_receipt`, what fraction the method returns.
2. Report **per family**, never only pooled. A single pooled table may appear as a secondary summary.
3. Keep leakage exactly as it is — it is well defined and reproduced cleanly: a returned item counts as leaked when no receipt exists for that recipient with `received_at <= received_by` and `recorded_at <= known_at`.
4. Split the event-only gold family. Today, a question whose gold is a lifecycle event carries no support unit and is therefore scored as "must abstain". Applied uniformly, so no bias results, but returning the correction notice is arguably the correct answer. Score that family on its own terms: did the method return the notice.
5. Add a **stability check**: run each method twice and assert identical output. Any nondeterminism must be found now, not during the paid track.

**Acceptance.** The results file contains per-family breakdowns for every method; the round-3 numbers are reproducible as the corresponding subset; the event-only family is reported separately with its own definition stated in the protocol.

### WI-11 — Break the authorship circularity · M · blocks the strongest claims in Track E

**Why.** This is the deepest methodological issue remaining. In round 2, `visible_record` is a reference implementation of the same visibility policy as the Store, written by the same author from the same understanding. In round 3, gold is described as authored by an independent agent, which is better — but the specification itself still comes from the implementation's authors. If the specification contains a misconception, the system, the reference and the gold all share it, and every test passes.

**Steps.**

1. Write `benchmarks/SPEC-TRI-TEMPORAL.md`: the semantics in prose, with no code — half-open intervals, the three clocks, the rule that a lifecycle event affects a recipient only once delivered to that recipient, the precedence between recording time and receipt time, what happens when a retraction arrives before its replacement.
2. Hand **only that document** to a second agent or engineer who has not read `store.py`, `delivery_projection.py`, or any existing fixture. They implement the reference visibility function and author the gold.
3. Record in the result file: which model or person authored the reference, the prompt or brief they were given, and the SHA-256 of the specification handed over.
4. Where the two implementations disagree, do not silently fix the reference. Each disagreement is either a specification ambiguity (fix the specification, re-derive both) or a genuine bug (record it). Publish the disagreement log — it is evidence of the process working.

**Acceptance.** `SPEC-TRI-TEMPORAL.md` exists and is sufficient to implement the reference without reading the application; a disagreement log exists, even if empty; the reference author is recorded.

### WI-12 — Preregistration and statistics · S · blocks Track E

**Why.** Round 2 already predeclares a comparison reference and freezes a gate on DEV, which is most of the way there. Formalizing it makes the claim auditable rather than self-reported, and the multiple-comparison correction removes the one statistical objection currently disclosed but unaddressed.

**Steps.**

1. Create `PREDICTIONS.md` before any run of Tracks C–E, containing, per experiment: the hypothesis, the primary metric, the decision threshold, **what is expected to win**, and **what is expected to lose**. The round-2 documents already predict losses in prose; make it a table.
2. Commit it, then record its commit SHA and file hash in every result file produced by that experiment.
3. Apply Holm correction across each comparison family (6 systems × 3 datasets in cross-domain; 5 arms in the answer track). Report both raw and adjusted intervals.
4. Power: 500 questions per arm resolves a ±0.03 difference in a paired design at conventional levels. Do not run a full arm at n < 300.
5. Keep the paired bootstrap, the fixed seed, and the practice of publishing intervals that include zero.

**Acceptance.** Every Track C–E result file carries `predictions_sha256` and `predictions_commit`; adjusted intervals appear beside raw ones.

---

## Track D — Public, externally authored evaluation (API for the answer arms only)

### WI-13 — FANToM adapter · L · the highest-value item in this document

**Why.** FANToM (EMNLP 2023) is multi-party conversation where characters join and leave, so participants miss information shared in their absence — information asymmetry created by arrival and departure times, authored by someone else, publicly licensed, with questions that ask precisely *who is aware of what*: BeliefQ, AnswerabilityQ, InfoAccessQ. That is the delivery clock, with external gold. One good result here is worth more than any number of in-house fixture points, because it cannot be accused of being built to be won.

**Mapping.**

| FANToM | Chronoverse |
| --- | --- |
| Conversation turn | assertion, `recorded_at` = turn index or timestamp |
| Character present for a turn | receipt for that character, `received_at` = that turn |
| Character absent | no receipt — the fact exists in the ledger, invisible to them |
| Character rejoins | later turns generate receipts again; the gap stays permanently unfilled |
| InfoAccessQ / AnswerabilityQ | query scoped to that recipient, `received_by` = current turn |
| BeliefQ | requires an answerer — belongs to the answer track (WI-16), not retrieval |

**Steps.**

1. Write `benchmarks/fantom_adapter.py`: load the public dataset, build one ledger per conversation, derive receipts from presence intervals, emit queries in the existing fixture schema.
2. Retrieval track (no API): score InfoAccessQ and AnswerabilityQ as a retrieval problem — did the system return exactly the facts this recipient could access. Compare the same five methods as round 3: global temporal, scalar clock, post-projection filter, SQL receipts before projection, delivery projection.
3. Answer track (API, WI-16): feed each arm's retrieved context to the same answerer and score the dataset's own metrics.
4. Record the dataset version and its license, and keep the adapter faithful — do not drop question types that are inconvenient. Report the ones that do not map, and say why.

**Acceptance.** The adapter reproduces the dataset's own conversation and question counts exactly; the retrieval comparison runs on the full set; any excluded question type is listed with a reason in the protocol.

### WI-14 — LongMemEval head-to-head, including a Graphiti baseline · L · depends on WI-16

**Why.** LongMemEval (ICLR 2025) is 500 questions over 30–40 sessions (~115k tokens) or ~500 sessions (~1.5M tokens), testing information extraction, multi-session reasoning, **knowledge updates**, **temporal reasoning** and **abstention**. Knowledge updates and abstention map directly onto correction handling and empty-support behaviour. It is also the arena where Zep published its numbers, which makes it the natural place to establish whether Chronoverse is competitive with the state of the art rather than only with its own baselines.

**Steps.**

1. Run LongMemEval-S first. The M variant is a scale test and can wait.
2. Arms: (a) vanilla RAG over session chunks, (b) Chronoverse tri-temporal, (c) Graphiti/Zep as an external system, run through its own documented ingestion and query path with its own defaults.
3. The Graphiti arm is the one that requires care. Run it as its documentation prescribes; do not hand-tune it; if it needs an LLM for extraction, that is part of its cost and must be reported, alongside the fact that Chronoverse's ingestion path is different. State plainly what is and is not comparable — the round-1 LightRAG write-up is the model to follow here, and it is a good one.
4. Report per-ability scores, not only the aggregate. Chronoverse should be strongest on knowledge updates and abstention and may be weaker elsewhere; that shape of result is more informative than a single number.

**Acceptance.** Per-ability table for all three arms; explicit statement of every configuration difference between the Chronoverse and Graphiti arms; cost and latency reported per arm.

### WI-15 — Additional public corpora (optional) · M

StreamingQA for knowledge-time adaptation at scale; ChronoQA (CC BY 4.0, Zenodo DOI `10.5281/zenodo.17163857`, 5,176 questions over 300k news articles, Chinese — also probes the non-English gap the round-2 documents correctly flag); ArchivalQA or ChroniclingAmericaQA for large timestamped corpora. Take these only after WI-13 and WI-14 land; they broaden coverage but do not change the central argument.

---

## Track E — The answer-level experiment (paid API)

### WI-16 — Harness · L · depends on WI-09, WI-11, WI-12

**Why.** Every round so far measures retrieval. The theory's payoff is at the answer: a system that hands an LLM the wrong version of a fact produces a wrong answer, and nDCG cannot see it. This is also the only form of the result that a non-specialist reader can evaluate.

**Design rule.** One answerer, one prompt, one context budget, temperature 0. The **only** thing that varies between arms is what goes into the context window.

| Arm | Retrieval layer | Purpose |
| --- | --- | --- |
| A | Vanilla RAG: chunks with dates written in the prose, top-k by embedding | the ordinary industry baseline |
| B | Long context: every version of every relevant fact, plus an explicit "today is {valid_at}; you only know what was delivered by {received_by}" instruction | tests whether a large model can do this in-context |
| C | A + cross-encoder reranker | tests whether better ranking substitutes for temporal semantics |
| D | A + post-hoc metadata filter applied to retrieved results | the strong classical control; the §4 claim predicts this one fails on corrections |
| E | Chronoverse tri-temporal projection | the system under test |

Arms B and D carry the experiment. If B matches E, the advantage is cost and latency, not correctness. If D matches E, the filter-order result does not survive to answer level.

**Context budget.** Identical token budget for every arm, enforced and recorded. Arm B is the exception by construction — it receives more context, and that is the point of the arm; report its token count separately and never average it with the others.

**Prompt.** Fixed, versioned, hashed, identical across arms:

```
You answer strictly from the provided context.
Question: {question}
As-of date: {valid_at}
Context:
{context}

Rules:
- If the context does not support an answer, reply exactly: INSUFFICIENT EVIDENCE
- Do not use knowledge outside the context.
- Answer in one short sentence, then on a new line list the supporting context IDs.
```

**Scoring.** Deterministic first, model-judged second. Exact match and abstention are computed programmatically against gold. Only free-form equivalence goes to a judge model, and the judge never sees which arm produced the answer.

**Cost control.** A hard budget guard that counts tokens before dispatch and aborts at the cap; the cap and the actual spend are recorded in the result file. Use the Batch API throughout — none of this is latency-sensitive.

**Determinism and repeats.** Temperature 0, fixed seeds where the provider supports them, three independent repeats. Report the between-repeat variance; if it exceeds the between-arm difference, the experiment is underpowered and must not be published as a result.

**Acceptance.** A 50-question pilot completes end to end for under a few dollars, produces all metrics in WI-17, and the harness refuses to run when the prompt hash differs between arms.

### WI-17 — Metric definitions for the answer track · S

These must be written into the protocol before the first paid call, because each one is a decision about what counts as a failure.

1. **Stale-version rate** — the answer asserts a fact whose validity interval does not contain `valid_at`, while a correct version exists in the ledger. Computed by matching the answer's cited support IDs against gold version IDs; a citation outside the valid window counts as stale even when the prose happens to be right.
2. **Delivery leak rate** — the answer's content or citations depend on an item with no receipt for that recipient at `received_by`. This is the metric no competitor system can even express, and it should be reported first.
3. **Correction recovery** — restricted to the correction-sensitive families of WI-10: did the answer use the claim the recipient still legitimately holds, rather than a correction they have not received, or nothing at all.
4. **Answer exact match** — normalized string or numeric match against gold for closed-form questions.
5. **Correct abstention** — `INSUFFICIENT EVIDENCE` on no-support questions; and its mirror, **false abstention** on answerable ones. Report both; a system that abstains constantly scores perfectly on the first and must be caught by the second.
6. **Cost and latency per answered question**, per arm.

Report each metric per family and pooled. Never report a single headline number alone.

### WI-18 — Clock ablation · M · depends on WI-16

**Why.** This produces the sentence the theory needs, in a form that is falsifiable and attributable to one mechanism.

Same retriever, same model, same budget, same questions; remove one clock at a time:

| Configuration | Expected effect |
| --- | --- |
| Full tri-temporal | reference |
| valid + known, no delivery | delivery leaks appear; correction recovery drops |
| valid only | stale answers appear from evidence recorded after the question's knowledge boundary |
| no temporal filtering | all failure modes present |

**Acceptance.** A four-row table with confidence intervals, and a one-sentence result of the form: *"Removing the delivery clock causes X% of answers to use evidence the recipient had not received, and loses Y% of correction recovery."* If X is near zero, the delivery clock is not carrying the claim — report that.

---

## Track F — Architecture and product (no API)

### WI-19 — Three clocks in the index design · L

**Why.** `NEXT-ARCHITECTURE.md` already sketches versioned vectors with half-open knowledge intervals, which is the right shape. Add the delivery dimension now: retrofitting a per-recipient clock onto a two-clock index later is a migration, not a patch.

**Steps.**

1. Extend the versioned-vector design so a stored vector carries the text version identity and the coordinate intervals it is valid for, and so receipt state is a filter applied *before* lifecycle projection — which is exactly the ordering result from Part I §4, now expressed in the storage layer rather than only in the experiment.
2. Keep the exact scoped-search fallback permanently. Any approximate index must be measured against it for lost recall, not assumed equivalent.
3. ANN adoption criteria, to be written down and honoured: adopt only when exact candidate scoring is measured as the dominant cost at a corpus size the product actually has, and only with a published recall-loss measurement against exact search. Until then, the profiling already points at lexical tokenization and projection — continue there.
4. Redis stays out until multi-worker sharing is measured. If it ever enters, the cache key must include profile, all three coordinates, model identity, and ledger revision.
5. MCP surface: expose the three coordinates explicitly, including the recipient, so a caller can ask for a historical view and receive a result that is reproducible by construction.

**Acceptance.** A written design note with the migration path from the current schema, the ANN criteria, and the cache-key rule; no implementation required to close this item.

### WI-20 — Sufficiency and abstention as a separate experiment · M

**Why.** Round 3's best method still returns irrelevant received context: precision 0.4730, and only 10 of 18 empty-support questions abstain. The documents correctly decline to tune a classifier inside a retrieval experiment. It deserves its own round.

**Steps.** Calibrate on DEV only, freeze, evaluate on TEST — the round-2 gate protocol is already the right template and should be reused verbatim. Report the precision/coverage trade-off and the false-abstention cost, never precision alone. Keep it experimental and out of the application default until it is validated on representative user documents, exactly as currently stated.

---

## Sequencing, ownership and gates

| Order | Items | API | Effort | Gate before proceeding |
| --- | --- | --- | --- | --- |
| 1 | WI-01 … WI-05 | no | ~1 day | `make verify` green; provenance in every new result |
| 2 | WI-06, WI-07, WI-08 | no | ~2 days | tuned BM25 clears the acceptance thresholds |
| 3 | WI-09, WI-10, WI-11, WI-12 | no | ~3 days | fixture regenerates to the same hash; spec handed to a second author |
| 4 | WI-13 retrieval track | no | ~2 days | adapter matches the dataset's own counts |
| 5 | WI-16 pilot (50 questions) | ≈ $1 | ~1 day | metrics computable; between-repeat variance small |
| 6 | WI-16 full, WI-13 answer track, WI-18 | ≈ $25 | ~2 days | — |
| 7 | WI-14 LongMemEval incl. Graphiti | ≈ $15 | ~3 days | — |
| 8 | Report, kill-criteria review, WI-19, WI-20 | no | ~2 days | — |

Items 1–4 need no API key and can start immediately. Total paid spend across the programme, with three repeats and headroom, stays under $50 at current rates (Haiku 4.5 $1/$5 per MTok, Sonnet 5 $2/$10, Opus 5 $5/$25, Batch −50%, Voyage embeddings $0.12/MTok).

---

## Definition of done for the round

The round is complete when all of the following are true, and not before:

1. Every result file carries a git commit, a dirty flag, a predictions hash, and package freezes.
2. The BM25 baseline is at published strength, and the round-2 hybrid conclusions have been either confirmed or retracted in place.
3. The delivery fixture no longer saturates: at least one method is clearly separated from the others on a family with more than 50 questions in it.
4. At least one result comes from a dataset this team did not author — FANToM or LongMemEval.
5. The answer track reports stale-version rate, delivery leak rate and correction recovery for all five arms, with intervals, including the arms that beat Chronoverse.
6. The kill criteria in Part I §10 have been checked and the outcome written down, whichever way it went.
7. No document, file name, or heading contains quantum, collapse, observer-effect, or subjective-reduction vocabulary.

---

## What to hand a reader who has five minutes

One page, in this order: the three clocks and what each one answers · the filter-order finding with the six-case table · one external-dataset result · the kill criteria and which ones were survived · the one-line positioning:

> Retrieval that is correct for a particular recipient at a particular moment, including facts whose corrections have not yet reached them — with a measurement showing that filtering a conventional system's output afterwards cannot reproduce it.

Everything else is appendix.
