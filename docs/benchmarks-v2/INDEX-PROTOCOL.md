# Persistent vector index: production benchmark protocol

This experiment reruns the actual modified `chronoverse.store.Store.query` against the same 5,183 SciFact records and all 300 BEIR test queries used by v1. It does not patch the embedding function, cache, scorer, filters, graph traversal, or rank ordering. It writes only a temporary benchmark ledger. Existing application profiles and v1 artifacts remain untouched.

## Implementation under test

The ledger selects candidates by world, plane, perspective, valid time and knowledge time before passing their **projected** canonical text into semantic retrieval. A per-profile `derived_vectors` SQLite table stores reusable vectors keyed by model identity and SHA256 of that exact text. A later-visible evidence passage therefore has a different key from the earlier projection. The index never caches answers, determines eligibility, or replaces the immutable assertion/event ledger.

Model identity hashes the loaded local model/tokenizer artifacts, FastEmbed version, inference batch setting and vector representation version. Model artifacts remain fixed for a process lifetime: restart after changing model files. Rows store dimensions, format version, little-endian float64 BLOB and SHA256 checksum. Invalid rows are rebuilt. Model changes use a new key. The query never scans vectors for ineligible assertions.

Document cache lookups and exact cosine scoring use chunks of 256. Missing vectors are validated and atomically persisted in batches of at most 32; ONNX inference uses batches of four. Vectors are raw, and cosine divides the dot product by both norms, preserving the prior scoring formula, weights, threshold, rounding, and deterministic assertion-ID tie ordering. This is exhaustive exact scoring, not ANN search. Vector memory is bounded by chunk size; scalar result arrays and the pre-existing assertion candidate list still scale with candidate count. Derived rows accumulate on disk; automatic compaction is not implemented.

## Batch-size selection

`index-batch-pilot.json` records a warmed, unlabeled pilot on the same first 32 canonical corpus documents for batch sizes 32, 8, 4 and 1. Batch four was fastest in this small pilot and selected before inspecting retrieval labels. This is a performance choice on the shared local machine, not proof of an optimal general batch size. A preliminary batch-32 full-corpus run was interrupted before producing results because the cold-index rate was slow. Its incomplete temporary database is not used by the reported run.

## Data and timing

Dataset acquisition, document assertions, query text, qrels and canonical `_text` are reused from `benchmarks.scifact`. The runner verifies the canonical-text and dataset-file hashes against v1. The original dataset protocol, attribution and license remain in `docs/benchmarks/SCIFACT-METHOD.md`. No relevance labels choose model, parameters, corpus subset, query subset, or gates.

Run:

```sh
.bench-venv/bin/python -m benchmarks.index_scifact
```

The runner creates an isolated temporary SQLite ledger, then launches two separate Python processes:

1. **Fresh index:** import all records, time the first real query including model initialization, model fingerprinting and lazy document encoding/persistence. Then run all 300 unique queries.
2. **Reopened index:** reopen the same database in a new Python process, time its first query including model initialization/fingerprinting but using persisted document vectors. Then run all 300 unique queries.

Each process clears only the legacy query-embedding LRU after its cold pilot. Consequently every measured query in each 300-query pass includes fresh query inference. No query answers are cached. OS file/page caches are uncontrolled: reopened is process/model cold, **not disk cold**. Model inference, ledger projection, vector reads/checksums, exact cosine and ordinary ranking/graph result construction are inside query latency. Ledger import is timed separately. Fresh first-query time is a combined lazy-index cost, not pure encoder time.

Other local agents may run CPU-heavy experiments simultaneously. Treat the measured p50/p95 as this local run, not an isolated capacity claim. v1 latency comparisons use historical saved measurements; no fresh BM25/dense/RRF timing comparison is implied.

## Preservation and output

`index-results.json` contains source hashes, environment, index dimensions/parameters, both cold-query measurements, warm latency distributions, every query's top-10 IDs and rounded scores, metric aggregates, and comparisons against preserved v1 artifacts. Companion `index-fresh.json` and `index-reopened.json` retain full per-phase data.

All 300 v1 ranked ID lists are available for direct ranking comparison. V1 retained rounded scores only for its two stock pilot queries, so exact v1 score comparison is limited to those two. The runner also compares every fresh/reopened ID and rounded score. Tiny ONNX batch or matrix floating-point differences are possible; equality is measured and reported rather than assumed. Any ranking differences remain visible in the artifact.

Accuracy metrics are nDCG@10, Recall@5, Recall@10, MRR@10 and hit@1, using the existing tested metric implementation and all 300 nonempty-gold SciFact queries. This is document retrieval, not claim verification, temporal reasoning, generated-answer quality, or a full GraphRAG benchmark.

## Recorded result

Both complete 300-query passes preserved all v1 top-10 ID lists. Both available v1 stock-pilot rounded score lists matched exactly. All 300 fresh/reopened ID lists and rounded score lists also matched each other. Each pass recorded zero query-embedding cache hits and 300 misses.

The fresh first query took 946.186 seconds to initialize and fill 5,183 vectors under concurrent local benchmark load. The first query in a new process reopening those vectors took 2.144 seconds. Fresh warm p50/p95 were 1.422/2.696 seconds; reopened warm p50/p95 were 1.572/2.043 seconds. These warm timings are slower than v1's historical benchmark-only enlarged-cache measurements. This establishes persistence and ranking preservation; it does **not** establish a steady-state latency improvement over that historical cache arrangement.

A consistent SQLite backup of the completed ledger was retained at `.benchmark-data/index-v2-ledger.sqlite3` before the runner removed its temporary directory. SQLite's backup API captured all 5,183 assertions and committed vectors while the reopened worker was reading them. The backup connections were closed afterward. This avoids a WAL-unsafe main-file copy and allows subsequent profiling without re-encoding the corpus.

The exact persistent-index stage source files are retained under `docs/benchmarks-v2/source/persistent-index/`; their SHA256 values match `index-results.json`. Later production optimization changes are measured separately in `optimization-results.json`. The source snapshot is evidence for the historical stage and is not imported by the running application.
