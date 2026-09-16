# Four clock configurations — preregistered preparation protocol

> **STATUS · PROTOCOL (frozen)** — original dated 2026-09-13 01:00 · chain and replacements in [`00-START-HERE/VERSION-MAP.md`](../00-START-HERE/VERSION-MAP.md) · the ablation itself has not been run

This is a synthetic, fixed-pool context-gating ablation, prepared before any paid answer responses. There are **three clocks and four configurations**, not four independent clocks. It does not establish public benchmark performance, authorization enforcement, or a quantum mechanism.

| Configuration | Validity/lifecycle | Ledger recording | Recipient receipts |
|---|---|---|---|
| FULL | enabled | enabled | enabled |
| VK | enabled | enabled | disabled |
| V | enabled | disabled | disabled |
| NONE | disabled | disabled | disabled |

Use exactly the same 50 TEST questions selected in the five-arm pilot and the same frozen MiniLM top-50 typed candidate IDs/order from its manifest. No new embeddings, reranker, corpus, answer model or ranking weights are introduced. For each configuration, traverse those 50 candidates and return the first five eligible units. An empty/short result stays empty/short; no larger-pool backfill is allowed. This controls the ranked pool but cannot measure recall lost before that pool. FULL is this independent reference gate, not a renamed claim that it reproduces the Store's full-corpus top-five output.

All configurations use prompt v2, identical original query clocks, temperature zero, reasoning effort low, output cap and actual returned-model identity guard. The prompt always explains all three clocks. Thus NONE gives the answerer more potentially ineligible material but still allows it to enforce those rules itself; this measures retrieval assistance to the same answer task. It does not change the desired answer when a retrieval gate is disabled. Every included item retains its original raw receipt metadata in every configuration; filtering the receipt metadata itself is not an additional hidden experimental variable.

The validity gate enforces assertion intervals `[valid_from, valid_to)` and retires a target assertion for an effective correction/supersession/retraction. A notice can affect that decision only when it passes whichever recording/receipt gates are enabled. Removing a receipt gate can therefore *remove* an old assertion by revealing a globally recorded correction; candidate sets need not be nested. No receipt gate means no recipient restriction. Removing the ledger gate means source and receipt-log recording dates are not eligibility restrictions. World, plane and perspective remain fixed in every configuration.

Each raw assertion chunk, independently rankable evidence passage, and notice has a typed identity. Assertion chunks retain only evidence passing the enabled recording/receipt gates. Notices enter the context only when independently selected from the ranked pool; they do not receive replacement text. Standalone passages inherit the parent's original `[valid_from, valid_to)` interval when validity is enabled, but never require the parent's receipt, recording cutoff or lifecycle-active state. They are received source reports, not endorsed claims. Notices describe lifecycle actions and do not inherit that interval; their effective dates remain metadata. Only `supersede`, `correct` and `retract` notices retire a target; other event types do not. Date comparisons normalize offsets to UTC (naive/date-only values mean UTC). These item-type differences are explicit and held constant across configurations. Repeated context IDs collapse on first occurrence, without ranked-unit backfill.

Gold labels never affect candidate text, ranking or projection. The same external answer labels and citation equivalence groups score every configuration. Report literal closed-form answer matching separately from primary eligible support-group recall/completeness, supplementary strict typed-ID support, abstention, false abstention, cited unreceived/stale/unknown IDs, and truncation/failed-attempt counts. Orphan/event-only cases remain separate. Literal string matching and citation audits are not semantic answer evaluation or proof of no uncited leakage. No thresholds or prompts may be tuned on these TEST responses.

Offline inference has exactly three directional paired contrasts: `FULL - VK`, `FULL - V`, and `FULL - NONE`. The query is the paired unit; first average the three repeats within each arm and query, then difference arms. Repeats are not independent observations. For each metric, the three contrasts form one preregistered multiplicity family. Two-sided query-paired sign-permutation p-values receive Holm adjustment across those three tests. Confidence intervals are reported separately as raw 95% paired-bootstrap intervals and Bonferroni simultaneous intervals using two-sided alpha `0.05 / 3` (98.333333% per contrast); they are not called Holm intervals. Use 10,000 bootstrap and sign-permutation draws with seed 20260913. There is no study-wide correction across the distinct metrics, so metric-wise claims are not jointly controlled. `FULL - other` is positive-is-better except for false abstention, where lower is better.

A missing, truncated, non-stop, wrong-model, model-guarded, or budget-breaching attempt scores zero for closed-form answer, eligible support recovery, end-to-end, and correct abstention outcomes, preserving the planned query denominator. Citation audits and false-abstention behavior are unknown for such an attempt. An audit contrast requires all three repeats in both paired arms to be observed for that query; excluded pairs and reasons are counted, and false-abstention inference is descriptive when fewer than 30 complete query pairs remain. Every recorded attempt, including invalid attempts, remains in status, latency, and usage summaries. This policy is fixed before reading answer outputs.

Three repeats yield **600 requests** for 50 queries × four configurations. Produce an offline estimate before any network dispatch; use the same 8,192 input and 1,024 completion caps as A/C/D/E, with an explicit larger input cap only if preparation fails before dispatch. Do not truncate. The generator itself performs no paid requests. The user subsequently authorized the supplied provider and available models; a measured, explicit run reservation and exact model identity are still required for dispatch. Private-provider USD prices remain unknown.

```bash
python -m benchmarks.clock_ablation --source-manifest ANSWER_CONTEXT_MANIFEST.json
# Decompress the exact JSONL bytes, then estimate only:
python -m benchmarks.answer_experiment --mode estimate \
  --manifest CLOCK_CONTEXTS.jsonl --model MODEL \
  --arms FULL,VK,V,NONE --max-input-tokens 8192 --max-completion-tokens 1024
# After dispatch completes or stops, aggregate retained attempts offline:
python -m benchmarks.clock_answer_statistics \
  --manifest CLOCK_CONTEXTS.jsonl.gz --results CLOCK_RESULTS.json \
  --expected-response-model MODEL --output CLOCK_STATISTICS.json
```

The generator records fixture, prompt and source-manifest hashes, selected IDs per configuration, exact compressed/uncompressed output hashes and guarded source/runtime provenance. Offline tests cover cutoff equality, interval exclusivity, delayed correction, independent passage receipts, source recording, gold poisoning and the exact four-arm transport contract.
