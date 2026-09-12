# Native Cohere rerank on frozen SciFact candidates

Freeze this protocol and runner before all 300 scored calls. This is an explicitly hosted **system-upgrade comparison**, not a model-only comparison, and does not change the running answer pilot, its five arms, prompts or contexts. No new first-stage retrieval or generated-answer model is used.

## Inputs and fixed request

Use exactly the 300 official SciFact test query strings and the ordered top-50 candidate IDs already stored in `docs/benchmarks-v2/rerank-results.json`. Verify its canonical input SHA against `.benchmark-data/scifact/canonical-records.jsonl` (`34cafe42858e0df6aa8d2774707283f716a31861c65bdb325c5942bd0020317e`), and verify official query/qrel file hashes against that historical artifact. Require 5,183 unique canonical documents, exactly the official 300 query IDs, and 50 unique same-pool IDs for both historical rankings. Reproduce historical baseline metrics independently before publishing the comparison.

The native request is `POST https://openrouter.ai/api/v1/rerank`, model `cohere/rerank-v3.5`, original query, exact full canonical document strings in original candidate order, and `top_n: 50`. No local truncation or additional query instruction is applied. Expected response model is exactly `rerank-v3.5`, as reported by the authorized preflight. A chat response, alternate model, absent identity, missing index, duplicate/out-of-range index, or nonfinite score fails validation. Sort descending finite score and then document ID for deterministic ties. Preserve complete raw native responses, including any supplied truncation metadata; do not invent absent per-document truncation counters. Endpoint redirects are refused.

The provider documents a default document limit of 4,096 tokens and automatic truncation beyond that limit; the historical local MiniLM cross-encoder used a pair limit of 512. Sending the same raw strings therefore does **not** establish identical effective text coverage. This length/model/runtime difference is part of the system upgrade. Exact truncation counts are unknown unless the response explicitly supplies them. [Cohere rerank API](https://docs.cohere.com/v2/reference/rerank). OpenRouter exposes a native rerank capability separate from chat. [OpenRouter RAG documentation](https://openrouter.ai/docs/cookbook/evaluate-and-optimize/rag).

## Money, provenance and uncertain outcomes

The agent-selected planned reservation within the authorized experiment is **$0.01 per request × 300 = $3 maximum reservation**. Require explicit CLI `--max-usd 3` and a runtime-only credential file; never persist the key or its path in result artifacts. The small preflight's observed cost is not assumed to price every 50-document request. Every response must provide finite nonnegative `usage.cost`; verify it against its reservation and the cumulative budget. Missing cost or a charge over the reservation stops further dispatch and retains the raw response. Client checks cannot retroactively undo a provider's unexpected charge; $3 is the planned cap, not an unsupported billing guarantee.

One synchronous worker uses an exclusive checkpoint lock. Fsync a `pending` reservation before the network call. Cache identity binds exact endpoint, requested/returned model identities, request bodies, ordered documents, source/input hashes and budget. Revalidate cached native responses and rankings on resume. A timeout, HTTP error, invalid JSON, interrupted pending record, response/cost validation failure or budget breach blocks automatic retry. Never substitute chat or retry an uncertain possibly billed call. Preserve error type/status without printing remote error bodies or credential-bearing exception strings. Source, canonical text, query/qrel, protocol and runtime provenance are checked throughout and before publishing.

## Fixed evaluation and contrasts

Compute nDCG@10 independently from official graded qrels using gain `2^relevance - 1` and log2 discount; IDCG uses all judged positives, not only the candidate pool. Also report recall@10, MRR@10 and hit@1 descriptively. The three methods are the frozen original RRF top-50 order, its already measured local MiniLM cross-encoder order, and the hosted Cohere order. No candidate/qrel-dependent tuning is permitted.

Declare exactly two paired nDCG@10 contrasts: **Cohere minus original RRF** and **Cohere minus local cross-encoder**. The unit is one of the 300 queries. Use seed 20260913, 10,000 paired query bootstrap samples, raw percentile 95% intervals and Bonferroni 97.5% intervals for these two contrasts. Report two-sided paired sign-flip Monte Carlo p-values from 20,000 draws with add-one correction and Holm adjustment across the two contrasts. The sign-flip symmetry assumption and public-data training overlap limit interpretation. Keep all per-query ranks, scores and losses. Do not claim completion or summarize a selectively successful subset when a run stops.

Hosted latency is this run's network rerank-only elapsed time. Historical local measurements include a different machine/runtime/load and their recorded first-stage cost. Show protocols separately, never label them a controlled same-clock speed race. Report observed provider costs/search units; relevance scores are not truth probabilities.

```bash
# Safe preparation: no credential read and no network.
python -m benchmarks.openrouter_rerank --mode prepare
# Parent launches only from the frozen clean worktree with explicit runtime args:
python -m benchmarks.openrouter_rerank --mode run --key-file KEY_FILE --max-usd 3
```
