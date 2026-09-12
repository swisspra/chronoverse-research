# Cross-domain retrieval v3

This round tests a stronger lexical baseline and matched dense context lengths on the complete BEIR SciFact, NFCorpus, and FiQA TEST sets: 66,454 corpus rows and 1,271 queries. The protocol was committed before scoring in [`PREDICTIONS.md`](../../PREDICTIONS.md).

The lexical run uses Pyserini 2.4.0 with Anserini's `DefaultEnglishAnalyzer`, Porter stemming, the Lucene English stop set, BM25 `k1=0.9, b=0.4`, and equal weights for separate `title` and `contents` fields. Dense retrieval uses fixed-revision MiniLM and BGE models, normalized FP32 vectors, exhaustive dot product, and identical title-plus-newline-passage input. Hybrids use top-100 reciprocal-rank fusion with `k=60`. The primary metric is linear-gain nDCG@10, matching `trec_eval`/BEIR.

## Results

| Dataset | Tokens | Strong BM25 | MiniLM | BGE | BM25 + MiniLM | BM25 + BGE | Three-way RRF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SciFact | 256 | 0.6647 | 0.6451 | 0.7005 | 0.7040 | 0.7105 | **0.7175** |
| SciFact | 512 | 0.6647 | 0.6541 | 0.7127 | 0.7074 | 0.7118 | **0.7184** |
| NFCorpus | 256 | 0.3254 | 0.3167 | 0.3442 | 0.3490 | 0.3580 | **0.3594** |
| NFCorpus | 512 | 0.3254 | 0.3105 | 0.3438 | 0.3461 | 0.3593 | **0.3600** |
| FiQA | 256 | 0.2361 | 0.3687 | 0.3913 | 0.3698 | 0.3614 | **0.4042** |
| FiQA | 512 | 0.2361 | 0.3610 | 0.4035 | 0.3680 | 0.3627 | **0.4065** |

The strong lexical implementation reproduces the published Pyserini multi-field baselines within 0.0005: 0.6647 versus 0.665 for SciFact, 0.32545 versus 0.325 for NFCorpus, and 0.2361 versus 0.236 for FiQA. It also improves descriptively over the earlier regex-token `rank_bm25` baseline on all three datasets (0.6519, 0.3064, and 0.2167 respectively). The external reference is the [Pyserini BEIR two-click reproduction](https://castorini.github.io/pyserini/2cr/beir.html) and the [SIGIR 2024 BEIR resource paper](https://ehsk.github.io/assets/pdf/SIGIR_2024__BEIR_Resource.pdf); the larger Vespa figures cited in the review use a different engine and are not the reproduction target here.

Longer context does not provide a general improvement. Only FiQA BGE@512 beats BGE@256 after correction: mean nDCG@10 difference +0.0122, Holm-adjusted `p=0.0012`, Bonferroni simultaneous 95% interval `[+0.0037, +0.0213]`. The other five length contrasts cross zero in their simultaneous intervals. MiniLM@512 is a sensitivity cell because 512 exceeds that model's documented training/default sequence length.

The FiQA finding that lexical fusion can hurt BGE survives the stronger baseline and matched lengths. BM25+BGE minus BGE is -0.0299 at 256 tokens (Holm `p=0.0019`, simultaneous interval `[-0.0519, -0.0069]`) and -0.0408 at 512 (`p=0.0003`, `[-0.0625, -0.0186]`). The historical weak-lexical configuration is -0.0743 (`p=0.0003`, `[-0.0971, -0.0521]`). Three-way RRF is numerically best in every table row, but this round did not preregister a direct three-way-versus-BGE significance family, so that observation is not a confirmatory claim.

The primary matched-length families compare five non-reference systems against BM25+MiniLM for each dataset: 15 hypotheses at 256 and 15 at 512. The length family has six contrasts, and the FiQA hybrid-minus-BGE family has three. Two-sided paired permutation p-values receive Holm correction. Raw paired bootstrap intervals and separately labelled Bonferroni simultaneous intervals are both reported; they are not interchangeable.

## Truncation and limitations

Document fractions over 256/512 tokens are 71.0%/8.8% for SciFact, 78.8%/9.1% for NFCorpus, and 19.2%/4.2% for FiQA. No TEST query exceeds either limit. MiniLM and BGE use their own fixed-revision tokenizers; the equal numerical cap does not imply identical token sequences or training conditions.

FiQA contains 38 rows with empty title and passage. Anserini therefore indexes 57,600 of 57,638 rows; one empty row has a positive TEST judgment, and no evaluated system retrieves it in the top 100. This dataset defect is retained and disclosed rather than repaired with gold information. Dense systems receive the empty input through their ordinary tokenizer, while lexical retrieval has no terms to index.

Runtime comparisons are observational on one shared machine. MiniLM@256 and BGE@512 reuse byte-verified vectors from the previous round; BGE@256 and MiniLM@512 were newly encoded. Embedding latency therefore cannot be compared causally across cells. Potential model-training overlap with the evaluation datasets was not independently audited.

## Artifacts and verification

- [`cross-domain-summary.json`](cross-domain-summary.json) contains aggregate metrics, truncation statistics, cache provenance, and every inferential result without per-query rankings.
- [`cross-domain-results.json.gz`](cross-domain-results.json.gz) contains all per-query top-100 rankings and original run provenance. Gzip SHA256: `54986f0f4a83cf55cd5421661d7905a4626f4a43b1551962b91fd10ee9835179`; uncompressed JSON SHA256: `466865635a726b56d21d3dc01d16bc1a94c6d1b24d5980df4ac676f00aacb578`.
- [`verify_cross_domain_v3.py`](../../benchmarks/verify_cross_domain_v3.py) independently recomputes 108 aggregate metrics from official qrels and validates 36 system cells plus 39 inferential mean contrasts.

Run verification with:

```bash
.tools-venv/bin/python benchmarks/verify_cross_domain_v3.py docs/benchmarks-v3/cross-domain-results.json.gz
```
