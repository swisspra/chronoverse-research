# Hosted embedding extension: three complete public corpora

All 1,271 official queries were scored with `text-embedding-3-large`, 3,072 dimensions, exact normalized dot-product retrieval, 512 `cl100k_base` input tokens, document-ID tie-breaking and self-document exclusion. This is static document retrieval; it does not test three-clock answer reasoning.

| System, nDCG@10 ×100 | SciFact | NFCorpus | FiQA |
| --- | ---: | ---: | ---: |
| Strong BM25 | 66.47 | 32.54 | 23.61 |
| Local BGE at512 | 71.27 | 34.38 | 40.35 |
| Local three-way RRF at512 | 71.84 | 36.00 | 40.65 |
| Hosted text-embedding-3-large | 78.10 | 41.93 | 54.85 |

Comparisons with local systems are descriptive: equal token caps use different tokenizers, and hosted aliases do not identify immutable weights. The hosted model size/training and effective text coverage differ. No public leaderboard equivalence or unique Chronoverse gain is claimed.

The FiQA run independently verifies all648 query rankings and nDCG values. It retains57,638 corpus rows, excludes38 empty source strings from API/ranking, and truncates2,193 documents (3.80%). Empty rows use explicit zero-vector sentinels; their IDs are not retrieved. Source/repair/protocol provenance is frozen at `9ece9b924d54a926dde98aa2f0400fb1ce8c3343`, clean. Earlier SciFact/NFCorpus artifacts retain their original separate provenance.

Final shared accounting records1,060 completed embedding requests and **12,071,548 reported input tokens across the extension**, including cached earlier stages. This is cumulative, so do not add earlier cumulative reports again. Two prior dispatch charges remain unknown: one empty-input HTTP400 and one timeout subsequently retried exactly once with both reservations retained. All reservations total55,811,356 conservative input tokens under the80,000,000 cap. Private-provider USD prices are unavailable. Cache reuse and concurrent local workloads make timing observational.

FiQA raw SHA256: `a716f370e0490a687b3a92b8571dbebee5b52e767cf7135c452799e3b4b31b5a`.

[SciFact raw result](hosted-scifact-results.json) · [NFCorpus raw result](hosted-nfcorpus-results.json) · [FiQA raw result](hosted-fiqa-results.json) · [Frozen protocol and recovery amendments](HOSTED-PROTOCOL.md)
