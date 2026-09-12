# Chronoverse comparative benchmark — September 12, 2026

The first measured result is encouraging retrieval quality with a serious performance limitation. On the complete public SciFact retrieval split, Chronoverse scored slightly above the tested hybrid baseline, but that difference is statistically uncertain. Its temporal filtering worked on the generated scenarios, and properly filtered conventional retrievers matched it. These results do not establish superiority over GraphRAG systems.

Open [the interactive report](index.html) to switch tracks, inspect individual queries and download the underlying results. All runs used isolated benchmark environments and temporary ledgers. Application rankings, demo data and uploaded profiles were left unchanged. No paid inference or answer generator was used.

## 1. Public evidence retrieval: SciFact

We downloaded the official BEIR archive, verified its published MD5, and recorded SHA-256 hashes. The run used **all 5,183 abstracts and all 300 test queries**, with public relevance judgments. This task retrieves relevant scientific evidence; it does not decide whether the claim is true. Sources: [BEIR datasets](https://github.com/beir-cellar/beir/wiki/Datasets-available), [SciFact paper](https://aclanthology.org/2020.emnlp-main.609/), [dataset card and license](https://huggingface.co/datasets/BeIR/scifact/blob/main/README.md).

Every method saw the same canonical assertion text, with title and abstract as evidence. Dense methods used the existing local 384-dimensional MiniLM model. BM25 used the real `rank-bm25` package with default scoring parameters and the same tokenizer as Chronoverse. The hybrid used reciprocal-rank fusion with k=60. No parameters were tuned against the test labels. See [the full protocol](SCIFACT-METHOD.md).

| Method | nDCG@10 ↑ | Recall@10 ↑ | Indexed-query p50 ↓ |
|---|---:|---:|---:|
| BM25 | 0.6518 | 0.7740 | 8.0 ms |
| Dense MiniLM | 0.6115 | 0.7583 | 6.8 ms |
| RRF hybrid | 0.6734 | 0.8151 | 15.5 ms |
| Chronoverse Store, **benchmark-only document cache** | 0.6920 | 0.8161 | 270.3 ms |

nDCG rewards relevant documents near the top; Recall measures how many labeled relevant documents were found. Timing includes fresh query embedding for dense methods and excludes document indexing. RRF timing sums its measured components. The machine was shared with other local workloads, so these are exploratory timings rather than a capacity guarantee.

Chronoverse's nDCG difference over RRF was **+0.0186**, with a paired query-bootstrap 95% interval of **−0.0076 to +0.0437**. The interval includes zero: this run does not establish a reliable advantage over the hybrid. The difference over this BM25 configuration was +0.0401, with interval +0.0109 to +0.0692. These are descriptive intervals for this dataset, without a multiple-comparison adjustment.

### Stock performance is much slower than the table

The production embedding cache holds 2,048 entries. The 5,183-document corpus exceeded it, and sequential access evicted embeddings before they could be reused. Two unmodified full-corpus queries took **32.19 and 29.51 seconds**. Each produced **zero cache hits and 5,184 misses**, including the query. Two samples are a diagnostic, not a latency distribution.

To finish all 300 accuracy queries, only the isolated benchmark process used an unbounded document cache around the original embedding function. Query embeddings remained fresh. The actual `Store.query` scoring/filtering/ranking code ran unchanged. Both pilot queries retained exactly the same top-10 IDs and scores. The cached table row therefore measures that benchmark configuration, not current app performance. Even with this adaptation, its median was about 17 times the tested RRF median.

SciFact records contain document-to-abstract graph links, not an extracted scientific entity graph. This experiment does not demonstrate a graph-reasoning benefit. Raw measurements: [results](scifact-results.json), [stock pilot](scifact-stock-pilot.json), [illustrative wins and losses](failure-cases.json).

## 2. Generated temporal capability diagnostic

The second track contains **204 assertions, 36 lifecycle events and 252 queries**: **21 scenario templates instantiated for 12 synthetic entities**. There are 216 answerable queries and 36 with no relevant answer. Gold IDs were specified by scenario design, then checked with independent tests; the system under test did not generate the labels.

The cases cover changing facts, exclusive interval ends, late corrections, retractions, future knowledge, worlds, epistemic planes, perspectives, conflicting sources and theory domains. Queries use exact entity/predicate wording and explicit coordinates. This is deliberately easier than natural-language temporal QA and is not an independent public benchmark.

| Method | Relevant result at rank 1 ↑ | Coordinate-ineligible returned records@10 ↓ | Empty-query abstention ↑ |
|---|---:|---:|---:|
| BM25, unfiltered | 61.1% | 47.6% | 0/36 |
| Dense, unfiltered | 61.1% | 55.4% | 0/36 |
| RRF, unfiltered | 61.1% | 49.3% | 0/36 |
| Actual LightRAG custom-KG retrieval, unfiltered | 61.1% | 63.8% | 0/36 |
| BM25 / dense / RRF + reference pre-filter, **each** | 100% | 0% | 0/36 |
| Chronoverse stock | 100% | 0% | 0/36 |
| LightRAG candidates + reference post-filter | 81.9% | 0% | 4/36 |

Rank-1 accuracy is measured only on the 216 answerable queries. Coordinate violations are the fraction of returned records incompatible with the requested time/world/plane/perspective, across all queries. Neither is an answer-generation score.

The engineered reference filters receive the same metadata/events as Chronoverse and never inspect gold relevance IDs. Matching results from these strong filtered baselines show that the value here is explicit data semantics and filtering, not evidence of uniquely superior reasoning. The unfiltered systems were not given an executable temporal policy; their results describe that configuration's capabilities.

All systems found every relevant answer within the first 10 results in this easy fixture. That does not mean every returned record was useful. Chronoverse's returned-set precision was 10.6% because it generally returned 10 records for questions with one or two relevant records. It also returned unrelated context for all 36 empty-answer queries. This is a retrieval/abstention limitation; no LLM was run to determine whether it would incorrectly answer from that context.

### Actual LightRAG, with an explicit adaptation boundary

We installed and ran **LightRAG 1.5.7** through `ainsert_custom_kg` and `aquery_data`, using its local JSON, NanoVectorDB and NetworkX stores. Its graph used assertion hubs to preserve provenance for changing claims. A supplied graph and query keywords bypassed extraction; an LLM trap confirmed zero LLM calls. This is real library execution on a caller-supplied KG, not an end-to-end LightRAG document-ingestion benchmark. Source: [official LightRAG repository](https://github.com/HKUDS/LightRAG).

LightRAG retrieved 20 candidate chunks; shared metrics score the first 10. The reference post-filter applies the requested metadata/events to those 20 saved candidates, then retains up to 10. It is a separate adapter, not a native LightRAG feature, and cannot recover records omitted from that candidate pool. This differs from pre-filtering the whole corpus.

LightRAG's run encoded query/keyword text during requests, whereas the small temporal baseline run used warmed document and query embeddings. Their latency figures must not be interpreted as a fair speed race. No end-to-end latency is claimed for the derived post-filter. Raw results: [temporal baselines](temporal-results.json), [LightRAG](lightrag-results.json), [post-filter adaptation](lightrag-filtered-results.json).

## What to do next

1. **Fix persistent vector indexing and candidate scoring.** Increasing the LRU alone postpones the same problem. Persist document vectors, retrieve candidate IDs efficiently, and retain time/scope checks before final ranking.
2. **Measure and improve abstention.** Add an explicit insufficient-evidence decision; returning temporally eligible context is not the same as answering the question. Tune thresholds on a separate development set.
3. **Broaden temporal evaluation.** Add paraphrases, multi-hop questions, chained corrections, delayed supersession, late evidence and exact knowledge-boundary cases. Run a public temporal/memory benchmark with a fixed answer model and measured ingestion cost.

[Graphiti](https://github.com/getzep/graphiti) is especially relevant because temporal graph memory is its stated focus. It and [Microsoft GraphRAG](https://microsoft.github.io/graphrag/) were researched but **not run** in this bounded offline experiment. Their proper ingestion/query stacks need additional model/service setup. No scores from published vendor benchmarks were substituted, and LightRAG is not presented as a Microsoft GraphRAG proxy.

## Reproduce and audit

From the project root, use the existing isolated environments:

```bash
.bench-venv/bin/python -m benchmarks.scifact
.bench-venv/bin/python benchmarks/generate_temporal.py
.bench-venv/bin/python -m benchmarks.temporal
.bench-lightrag-venv/bin/python benchmarks/lightrag_compare.py
.bench-venv/bin/python -m benchmarks.filter_lightrag
.bench-venv/bin/python -m benchmarks.failure_cases
.bench-venv/bin/python benchmarks/render_report.py
.bench-venv/bin/python -m pytest benchmarks/tests benchmarks/test_temporal_fixture.py -q
```

Environment package freezes, dataset/model/source hashes and fixed seeds accompany the scripts/results. The complete benchmark validation suite passed 266 tests at this stage. Most are independent fixture checks; a high test count does not increase the number of distinct scenario templates. Public source data stays under `.benchmark-data/`; the application never imports it into user profiles.

Serve the interactive report locally:

```sh
backend/.venv/bin/python -m http.server 8002 --bind 127.0.0.1 --directory docs/benchmarks
```

Open http://127.0.0.1:8002/.
