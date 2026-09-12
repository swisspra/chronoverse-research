# OpenRouter native Cohere rerank: verified result

Cohere improves ranking on the same 300 SciFact queries and original 50-document candidate pools. This is a hosted system upgrade, not a temporal-reasoning or answer-accuracy test.

| System | nDCG@10 ×100 | Recall@10 ×100 | Hit@1 ×100 |
| --- | ---: | ---: | ---: |
| Original RRF order | 67.34 | 81.51 | 53.33 |
| Local MiniLM cross-encoder | 68.86 | 82.56 | 56.33 |
| Cohere rerank v3.5 via OpenRouter | 77.37 | 87.69 | 66.67 |

| Paired nDCG contrast | Difference, percentage points | Bonferroni 97.5% interval | Holm p |
| --- | ---: | ---: | ---: |
| Cohere minus original RRF | +10.04 | +6.41 to +13.68 | 0.000100 |
| Cohere minus local cross-encoder | +8.51 | +5.39 to +11.76 | 0.000100 |

All 300 requests completed. API-reported rerank cost was **$0.300** (300 search units), below the $3 planned reservation. The separate initial transport probe reported $0.001; total observed OpenRouter usage for this probe plus comparison is $0.301. Retrieval/embedding costs are excluded. Network rerank-only latency was mean 0.896 seconds, p50 0.857 seconds and p95 1.179 seconds; historical local timings use a different scope and machine load.

The requested model was `cohere/rerank-v3.5`; every native response returned `rerank-v3.5`. Full original canonical strings were sent without local truncation. Cohere documents a default 4,096-token document limit versus the local cross-encoder's 512-token pair limit. This model/text-coverage/runtime confound prevents a model-only claim. Provider training overlap with public SciFact is unknown. The running answer pilot retains its original local reranker arm; this result does not retroactively change that arm.

The runner and protocol were frozen at `3c2f1301ab5b206ceffce12d10c3f98fc0b919bb` before scored calls. A separate verifier reproduced all 15,000 native score/index mappings, all rankings and qrel metrics, paired bootstrap/sign-flip statistics, costs and source hashes. It checks artifact consistency, not provider billing authenticity.

[Exact raw result](openrouter-rerank-results.json) · [Independent verification](openrouter-rerank-verification.json) · [Frozen protocol](OPENROUTER-RERANK-PROTOCOL.md)
