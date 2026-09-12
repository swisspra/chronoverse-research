# User-provided external review

The user supplied **“Chronoverse — independent review and proposed next round”**, dated 2026-09-12, as a review and implementation proposal. This page attributes statements to that document. The repository has not authenticated the reviewer's identity or credentials, obtained its separate scoring code, or replayed the external execution. “Reported as externally reproduced” below describes the document's claim, not a new verification performed here.

The document says its reviewer wrote scoring code from the published protocols, read official BEIR relevance judgments directly, and reconstructed receipt visibility from the frozen fixture without importing the project's scoring functions.

| Figure or check | Reproduction reported in the supplied document |
| --- | --- |
| V1 SciFact BM25 / dense / RRF / Store nDCG@10 | 0.6518 / 0.6115 / 0.6734 / 0.6920; Recall@10 also matched |
| V2 cross-domain | All 18 nDCG@10 values matched |
| V2 temporal | Precision/recall, 36/42 empty abstentions and 4/72 false abstentions matched |
| Reranking | Mean nDCG difference +0.015268 matched; a separate bootstrap gave an interval including zero |
| Production index and optimizations | All 300 top-10 lists and nDCG 0.691969 matched across four runs |
| Recipient receipt diagnostic | Global leakage 24/50 questions and 62 returned item appearances; zero leakage for receipt-aware methods |
| Receipt support accounting | 30/36, 29/36 and 35/36 support units; published precision values matched |
| SQL control and delivery adapter | Top-5 IDs/scores and candidate projections matched for all 50 questions |
| Dataset and test inventory | Official SciFact archive MD5 and split counts matched; 77 backend and 579 benchmark tests were collected |
| DEV/TEST split | No entity or scenario-family overlap; the reviewer reported no test-label tuning path |

The review's main interpretation is that **filter order** is the useful result: receipt filtering before lifecycle projection recovers six support units that filtering after global projection cannot restore. The matching SQL control shows the same semantics can be implemented conventionally. This is a synthetic retrieval finding; an answer-level or public-dataset advantage still needs its own test.

The supplied proposal also recommends stronger lexical baselines, matched encoder context lengths, clearer provenance, larger delivery fixtures and externally authored evaluation data. Its literature, pricing and future-work assertions are proposals to check separately, not measurements added to the repository by this summary.

In-repository verification is described as a **second implementation in this repository**. Another agent or another scoring function does not establish organizational independence. See [round-two results](benchmarks-v2/README.md) and [delivery results](benchmarks-delivery/README.md).
