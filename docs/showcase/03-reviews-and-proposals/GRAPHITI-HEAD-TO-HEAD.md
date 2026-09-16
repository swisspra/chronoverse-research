# Native Graphiti head-to-head — delivery clock on the correction families

> **STATUS · CURRENT** — original dated 2026-09-13 02:13 · chain and replacements in [`00-START-HERE/VERSION-MAP.md`](../00-START-HERE/VERSION-MAP.md) · separate track from the as-of pilot

Run date 2026-09-13. External review run; nothing in `SCGC/Chronoverse` was modified.
Scripts and raw output: `~/Desktop/Claude/Temp/gh_cases.py`, `gh_full.py`, `gh_full.jsonl`.

## Setup

| | |
| --- | --- |
| System under test | graphiti-core **0.30.2** (native open source, not hosted Zep) |
| Graph store | Neo4j Community 5.26.2 from the team's `.runtime/graphiti-neo4j`, bolt 17687 |
| LLM | `google/gemini-2.5-flash` via OpenRouter, `structured_output_mode='json_object'`, 75 s timeout, 1 retry |
| Embedder | local MiniLM (fastembed), no paid embedding calls |
| Reranker | order-preserving stub, so no extra model calls |
| Cases | the **175 correction-family TEST questions** from the frozen `delivery-v3` fixture |
| Spend | **$1.91** for the full 175-case run; $3.27 total including pilots and probes |
| Wall clock | 716 s at concurrency 6 |

Two arms, same Graphiti build, same LLM, same embedder, same question:

- **shared** — one graph holding everything the shared ledger knows by `known_at`, including the correction or retraction notice. This is Graphiti as shipped.
- **per_recipient** — one `group_id` per recipient, holding only what that recipient had actually received by `received_by`. This is Graphiti emulating a delivery clock by partitioning.

Scoring: the recipient-correct value string appears in an edge fact that is visible at the query's `valid_at` (`valid_at <= q`, `invalid_at` unset or `> q`, `expired_at` unset).

## Result

| Family | n | shared | per_recipient | shared: Graphiti did invalidate |
| --- | ---: | ---: | ---: | ---: |
| delayed_correction | 75 | 22 (29.3%) | **50 (66.7%)** | 69 (92.0%) |
| delayed_retraction | 50 | **41 (82.0%)** | 33 (66.0%) | 44 (88.0%) |
| historical_event_receipt | 50 | 33 (66.0%) | 34 (68.0%) | 50 (100.0%) |
| **total** | **175** | **96 (54.9%)** | **117 (66.9%)** | 163 (93.1%) |

Paired: per_recipient-only wins 55, shared-only wins 34, exact McNemar two-sided **p = 0.033**.
Neither arm ever returned zero visible edges, so nothing is explained by empty retrieval.

## Reading it honestly

1. **On delayed corrections the delivery clock works inside Graphiti**: 29.3% → 66.7%. Graphiti applied the correction in 92% of those shared-graph cases, and once it did, the recipient's still-valid earlier claim was gone. Partitioning by recipient restores it. This is the same mechanism the deterministic analysis predicted.
2. **On delayed retractions the result reverses** (82.0% shared vs 66.0% partitioned). A retraction notice is not modelled by Graphiti as an invalidation of the retracted fact — the LLM tends to add a notice edge and leave the original standing — so the shared graph keeps the gold value by accident. The partitioned arm has fewer episodes and loses some gold facts to extraction noise instead. The shared arm's score here is not correct temporal behaviour; it is a miss that happens to land on the right answer.
3. **The dominant error is not temporal at all.** Even the partitioned arm only reaches ~67%: roughly a third of gold facts never survive Graphiti's LLM extraction, entity resolution and hybrid search. That noise floor is large enough to swamp the effect being measured, which is why the overall gap is 12 points rather than the near-total gap the deterministic model shows.
4. **Contrast with the deterministic comparison.** Modelling the same 175 cases with the bitemporal rules alone — no LLM in the loop — gives 0/175 for a single shared graph and 175/175 for per-recipient partitions, and Chronoverse's own store scores 174/175 because it retrieves ledger records directly and never re-extracts them. The gap between that and the numbers above is a measurement of Graphiti's extraction channel, not of temporal semantics.

## What this does and does not establish

Establishes: a delivery clock changes answers inside a third-party temporal knowledge graph, measurably and in the predicted direction on the family it was predicted for; Graphiti 0.30.2 has no recipient dimension (`EntityEdge` carries `created_at, expired_at, valid_at, invalid_at` and `group_id` only, and `SearchFilters` exposes exactly those four temporal fields); and the emulation route costs one graph partition per recipient — on this fixture 152,048 ingested item-instances against 7,314 ledger records, a 20.8× replication, with 6,085 lifecycle-event replays against 611 events, each of which is an LLM extraction in Graphiti's pipeline.

Does not establish: that Chronoverse retrieves better than Graphiti. The arms differ in ingestion model, not only in clocks, and Graphiti's extraction loss is the larger term. A like-for-like quality claim needs either the same extraction pipeline on both sides or a comparison that scores answers rather than edges.

## Operational notes for the team

- The **kuzu backend of graphiti 0.30.2 is unusable**: `KuzuDriver` has no `_database` attribute, so `add_episode` raises immediately, and the full-text index `edge_name_and_fact` is never created. Upstream has deprecated it. Neo4j or FalkorDB only.
- **`json_schema` mode fails through OpenRouter** to OpenAI/Azure providers — Graphiti's schemas omit `additionalProperties: false`. `json_object` works, at the cost of occasional `EdgeDuplicate` validation errors; three attempts per case absorbed all of them (0 unresolved errors in 175 cases).
- **Single-entity episodes produce no edges.** A fixture fact shaped subject-predicate-numeric-value yields one entity and nothing else. Episodes had to name a second party ("submitted to the Regional Operations Center") before any edge existed. Any future Graphiti comparison must state this adaptation, because it changes what is being compared.
- Set an explicit client timeout. Without one the default is 600 s and a single stalled request blocks a worker for ten minutes.
- The Neo4j instance was stopped when this run began; it was started with the team's own helper and **left running**. My data was removed afterwards (`group_id` prefixes `hh`, `probe-`); only the existing `lme_s_*` group remains.
