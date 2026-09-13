# Next-round research checkpoint

[Open the five-minute evidence review](index.html). This round has measured retrieval results and a completed 50-question answer pilot. The original pilot stopped after 647 attempted slots, including one timeout; a [frozen continuation amendment](ANSWER-CONTINUATION-AMENDMENT.md) permitted only the 103 never-dispatched slots, and the timeout remains an unknown outcome that was never retried and counts as a failure. All 750 planned slots are now accounted for and scored: [answer results](ANSWER-RESULTS.md), [audit](answer-continuation-audit.json), [summary](answer-pilot-summary.json). A second round then removed the ranking confound those results carried, raised the completion budget and repeated the comparison on three answerers: [round-2 answer results](ROUND2-ANSWER-RESULTS.md). The full programme is still not complete: answer-level clock ablations, the full-500 answer run and a native Graphiti/LongMemEval head-to-head remain open.

The strongest supported finding is about operation order. A recipient receipt filter applied before lifecycle projection preserves legitimate older claims that a filter applied after global retirement cannot recover. A conventional SQL implementation using that order matches Chronoverse on all 658 measured queries. This is evidence for the rule, not a unique graph-reasoning advantage.

## Work-item status

| Review items | Status | Evidence and limits |
| --- | --- | --- |
| WI-01–03: Git, provenance, review disclosure | Implemented | Import tag preserves historical evidence; new runs record source commits, hashes and environment. Existing pre-Git results are not represented as preregistered. |
| WI-04: delivery terminology | Implemented with historical exception | Active code/docs use delivery terminology. Immutable historical raw results/source snapshots keep original vocabulary; the previous report URL redirects. |
| WI-05: unified verification | Implemented; expanding for new artifacts | `make verify` covers application tests, benchmark tests, historical verifiers and frontend build. New artifact verifiers also have corruption tests. |
| WI-06–08: strong lexical and length controls | Measured | [36 cells on three complete public corpora](../benchmarks-v3/README.md). FiQA hybrid loss persists with strong BM25; input length alone does not explain BGE performance. |
| WI-09–10: scaled fixture and metrics | Measured | [500 TEST, 108 DEV, 50 compatibility cases](../benchmarks-delivery-v3/README.md); all six arms stable across two repeats; per-family metrics retained. Distinct scenario variants share nine parent mechanisms. |
| WI-11: separate reference author | Implemented with disclosed limits | Specification-only fresh model conversation produced a reference and 12 authored cases. Corrections and model-routing identity are disclosed. The 500-case fixture remains team-authored; reference validation does not remove shared-specification bias. |
| WI-12: preregistration and statistics | Implemented for completed comparisons | Commit/hash recorded; Holm-adjusted p-values and separately labelled simultaneous intervals. Sample size does not guarantee power. |
| WI-13: FANToM | Diagnostic complete; answer track pending | Full public label inventory and gold-free presence mapping. No passage qrels exist, so no invented retrieval nDCG or official leaderboard score is reported. This diagnostic does not complete the proposed retrieval/answer head-to-head. |
| WI-14: LongMemEval / Graphiti | Local retrieval complete; native smoke verified | [500-question local diagnostic](../benchmarks-longmemeval/README.md) complete; strict session-date filtering reduces support-session recall. Native end-to-end comparison remains pending. 23,867 session instances. Native extraction can require several LLM calls per episode. Two native episodes ingested and searched successfully (21 API calls). No public Graphiti accuracy score or private dollar cost is invented. |
| WI-15: extra corpora | Deferred, optional | Follow full public answer experiments before broadening datasets. |
| WI-16–17: answer harness and metrics | Pilot complete, scored | Five fixed arms, 50 questions, three repeats; budget/checkpoint/model-identity guards. Literal answer matching and citation audits do not measure all semantic errors. The original 750-slot pilot stopped after 647 attempts; a bounded continuation finished the 103 undispatched slots, and all 750 are scored with 611 complete, 138 truncated/invalid and 1 uncertain. Full500 contexts are independently verified with byte-identical pilot overlap; paid full500 inference and blinded adjudication remain pending. |
| WI-18: clock ablation | Four-mode contexts frozen | Four fixed-pool configurations are implemented; generated answers and intervals are required before any causal answer-level statement. |
| WI-19: index and cache design | Written | [Three-clock migration, exact fallback, ANN criteria, cache key and MCP coordinates](THREE-CLOCK-INDEX.md). Redis remains deferred until shared-worker benefit is measured. |
| WI-20: sufficiency | Measured negative result | DEV-only calibration frozen in Git before TEST. Correct empty retrieval remains 0%; the gate reduces coverage without solving abstention. Keep it out of application defaults. |

## Kill-criteria review

1. **Strong BM25 erases the FiQA hybrid loss:** it does not. The loss survives at both matched lengths; the larger historical weak-baseline loss is reduced. See the local comparison's intervals and preregistered families.
2. **Long-context answers match delivery-aware answers:** not survived on this pilot. Arm E exceeds arm B by +0.413 closed-form accuracy and +0.430 end-to-end recovery, Bonferroni intervals excluding zero, Holm p = 2.0e-04. The caveat is stated in the results: arm B lost 45.3% of attempts to completion truncation under the frozen 1,024-token limit, and among valid completions alone its accuracy is 0.780 against E's 0.875. Raise the completion limit before repeating.
3. **Post-filter answers match correction recovery:** not survived. Arm D completed every attempt and cited nothing unreceived or stale, yet recovered 0.333 end-to-end against arm E's 0.822 (+0.489, Bonferroni interval excluding zero, Holm p = 2.0e-04). Filtering retrieved output does not restore a claim that an undelivered correction already suppressed.

The additional clock ablation is still untested at answer level: its four-mode contexts are frozen but no answers were generated. Correct abstention rests on five query pairs and is not significant. The programme's final definition of done therefore remains open.

## Reproduction and limitations

[Predictions](../../PREDICTIONS.md), [tri-temporal specification](../../benchmarks/SPEC-TRI-TEMPORAL.md), [reference disagreement log](../../benchmarks/REFERENCE-DISAGREEMENTS.md), [answer protocol](ANSWER-PROTOCOL.md), [FANToM protocol](FANTOM-PROTOCOL.md), and [proxy transport audit](PROXY-CAPABILITIES.md) separate claims from preparation.

Compressed artifacts retain original bytes and both hashes. A result's `git_dirty: true` can truthfully record its own earlier generated outputs; the accompanying explicit generated-output exemption is distinct from an allowed dirty source tree. Source changes during a guarded run prevent ordinary publication. Cache reuse is documented and makes cold/warm latency comparisons observational.

The private model provider's prices and invoice are unavailable. Actual returned token usage is recorded; private-provider dollars remain unknown, and no claim is made that the review's proposed total budget covers native Graphiti ingestion. No application defaults were promoted from this benchmark round.

## OpenRouter fallback

The private Cohere route still fails. OpenRouter native `cohere/rerank-v3.5` passed its transport probe and the separately frozen 300-query SciFact comparison completed: nDCG@10 77.37%, versus local cross-encoder 68.86%; API-reported cost $0.300 against the agent-selected $3 reservation. [Verified result and intervals](OPENROUTER-RERANK-RESULTS.md). [Frozen protocol](OPENROUTER-RERANK-PROTOCOL.md). The working private answer and embedding runs retain their original provider identities; any provider replacement is a separate attributed run.

The hosted embedding extension now covers all three corpora: SciFact78.10%, NFCorpus41.93%, FiQA54.85% nDCG@10. [Full comparison, provenance and cumulative accounting](HOSTED-RESULTS.md). These static retrieval gains are separate from temporal reasoning.

## Next study

After the current queue is audited, prepare Chronoverse versus native Graphiti **on** FANToM and LongMemEval, with a reproducible paper package. FANToM is a dataset, not a competing system. [Comparative study brief and publication gates](../paper/STUDY-BRIEF.md). No public paper submission is implied.

A [20-item closeout audit](ROUND-CLOSEOUT.md) records acceptance-condition deviations and remaining work. Artifact verification throughout this project means additional checks within the same team, as defined in the [evidence policy](../README.md); it is not unaffiliated replication.
