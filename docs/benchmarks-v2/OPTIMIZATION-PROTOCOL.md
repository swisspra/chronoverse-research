# Projection optimization after the persistent index

Low-overhead stage timers on ten complete production queries found vector reads, validation and exact cosine accounted for 11.56% of sampled wall time (0.120 seconds/query). Eligibility/projection averaged 0.251 seconds and lexical tokenization 0.395 seconds. The wrappers returned the original production results; all ten top-10 lists matched the full benchmark. See `index-stage-timing.json`. Shared CPU load and instrumentation limit capacity conclusions.

This experiment therefore adds no matrix LRU or lexical cache. It changes only temporal projection work in `Store`:

- Normalize valid-time and knowledge-time clocks once before candidate projection.
- Fetch lifecycle events with one SQL join using the same assertion scope and knowledge cutoff, replacing one event SELECT per candidate.
- Preserve recorded-time/event-ID ordering and effective-time lifecycle projection. Direct assertion detail still loads its own events through the existing path.

The SQL-trace regression initially failed with 30 event reads for 30 assertions; it now passes with bounded event reads while asserting historical retractions and future-recorded event exclusion. The complete backend suite passes 71 tests, and the two temporal fixture suites pass 569 tests.

Run `.bench-venv/bin/python -m benchmarks.optimize_index` to query all 300 SciFact test claims over the retained `.benchmark-data/index-v2-ledger.sqlite3`. No documents are re-encoded. A first query warms the reopened model/index path; then only the query-embedding LRU is cleared. Every measured unique query includes fresh query encoding.

`optimization-results.json` records all top-10 IDs and rounded scores, direct equality against the preceding full index run, accuracy metrics, p50/p95, query-cache counters, unchanged vector row counts, data hashes and source hashes. It preserves `index-results.json` unchanged. The historical baseline source is archived under `source/persistent-index/`.

The benchmark corpus has no lifecycle events, so the temporal regression fixtures supply lifecycle correctness coverage. A before/after difference on this shared machine cannot be attributed entirely to the code change. Exact ranking preservation is checked separately from performance.
