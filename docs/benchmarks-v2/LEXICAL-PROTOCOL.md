# Production bounded lexical postings cache

The token-postings pilot compared all 1,554,900 document scores (300 SciFact queries × 5,183 records) against the existing unique-token-overlap formula. Every score matched. The production implementation preserves that formula and tokenizer; it replaces repeated document tokenization with one Store-owned postings cohort.

`LexicalIndex.score` validates a SHA256 fingerprint over length-prefixed owner, document count and every exact projected UTF-8 text in its current order. Scope, knowledge time, valid time and event projection still execute first in Store. A changed cohort releases the previous postings before rebuilding. The cache stores no query answers, ranking or graph results. Duplicate documents retain separate positions; duplicate tokens count once per document and query.

A reentrant lock covers fingerprint checking, rebuilding and scoring, so concurrent requests cannot mix cohort positions. Each Store owns a separate cache. The default retained-object limit is 64 MiB per Store. Accounting includes the instance/attribute dictionary, scalar attributes, posting dictionary resizing, retained token strings, and posting-array allocated capacity. The limit is checked while building; oversized cohorts clear partial state and use the original exact overlap calculation. A rejected-cohort fingerprint avoids repeatedly attempting the same oversized build.

This is a bound on retained cache objects, not total process RSS. Caller-owned text, transient per-document tokenizer sets, build/query temporaries and result lists remain outside it. Several simultaneously retained Stores each have their own budget. No matrix LRU or answer cache is introduced.

Production verification includes six lexical tests (Unicode, repeats, order, exact text edits, over-budget fallback, array growth, concurrent cohorts, historical evidence, world filters, new assertions and separate profiles). Combined backend and temporal suites pass 646 tests. An independent reviewer additionally exercised 250 randomized Unicode/duplicate/empty cohorts concurrently with both 4 KiB and 64 MiB caps: 1,000 score calls matched exact overlap while retained bytes remained within the configured cap.

Run `.bench-venv/bin/python -m benchmarks.lexical_optimize_index`. It uses the existing retained SciFact vector database, performs one cold reopened query to initialize the model and lexical cohort, clears only the query-embedding LRU, then measures all 300 distinct queries with fresh query embeddings. Document vectors are reused. `lexical-optimization-results.json` compares every top-10 ID and rounded score with the preceding `optimization-results.json`, and records metrics, latency distributions, memory statistics, unchanged vector row counts, data/source hashes and all per-query results.

The historical bulk-projection stage source is archived under `source/bulk-projection/`, matching its saved hashes. Different stages ran sequentially on a shared machine, so observed before/after timing changes are not controlled causal estimates. Ranking/score equality is verified independently of timing.

## Recorded result

The complete production run preserved all 300 top-10 ID lists and rounded-score lists exactly; all accuracy metrics stayed unchanged. The retained lexical cache held 5,183 documents and 41,124 unique tokens in 9,412,564 bytes, below the 67,108,864-byte cap. Vector row counts remained 5,183 before and after the run. Query-embedding counters were zero hits and 300 misses.

The first reopened query, including model initialization and lexical-cohort construction, took 3.768 seconds. Warm p50/p95 were 0.800/1.492 seconds (mean 0.874). The preceding bulk-projection run measured 0.928/2.394 seconds. These are sequential shared-machine observations, not an isolated estimate of the cache's causal speedup. Exact source files matching the result hashes are retained under `source/lexical-postings/`.
