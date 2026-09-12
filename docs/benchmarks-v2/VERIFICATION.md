# Round-two verification

The coordinating agent ran the final cache/projection code regression suites:

```text
backend/.venv/bin/python -m pytest backend/tests -q
77 passed, 1 warning in 13.94s

.bench-venv/bin/python -m pytest benchmarks/tests benchmarks/test_temporal_fixture.py -q
579 passed in 8.20s
```

The warning is an existing Starlette test-client deprecation for AnyIO's BlockingPortal alias. Tests cover profile isolation, imports, historical evidence, immutable events, persisted vector reuse/corruption, exact lexical overlap, bounded cache fallback and temporal fixture consistency.

Another agent in this project additionally compared 1,000 concurrent randomized lexical-score calls with direct token overlap, including Unicode, duplicate texts, changing cohorts, and 4 KiB/64 MiB cache budgets. No mismatch or retained-budget violation was reported.

The completed artifact audit, browser checks, and live application restart are recorded below. Raw experiment outputs preserve the original timed implementation hashes; production source archives distinguish changes between runs.

## Live application after final production restart

Restarted `./scripts/dev.sh --no-build` to load persistent vectors, bulk event projection, and lexical postings. Actual HTTP and MCP network calls passed:

- HTTP `/health` and profile listing succeeded.
- HTTP `/api/query?profile_id=demo`, query `Harbor director`, plane `fact`, returned `fact-director-new`, `fact-location`.
- MCP at `http://127.0.0.1:8001/mcp` listed six tools; the same scoped search returned the same two IDs without an error.
- Existing profiles remain: demo: 17 assertions / 3 events; Document Sandbox: 3 assertions / 0 events. Verification did not add or modify ledger records.

## Independent artifact audit

`.bench-venv/bin/python -m benchmarks.verify_v2_artifacts` passed. It recomputed all 18 cross-domain aggregate metric triples directly from official qrels and saved IDs, checked all 1,271 queries and 100 unique candidates per system, and verified all 12 vector-array hashes, dimensions, finite values and unit norms. It also separately checked all 300 production ranking/score comparisons and both reranker metric triples with exact 50-document candidate-pool preservation. See `verification-results.json` for artifact hashes.

## Browser report checks

Ego browser exercised all four tracks, all three public dataset selections, DEV/TEST and gated/ungated controls, and inspected actual failure examples. All 47 local link checks returned HTTP 200. Desktop 1440×1050 and mobile 390×844 screenshots were visually inspected; the mobile document remains 390px wide and wide tables scroll within their containers. Screenshots: `report-desktop.png`, `report-mobile.png`.


[User-provided external review](../EXTERNAL-REVIEW.md) reports a separate recomputation of listed figures. This repository has not authenticated the reviewer identity or replayed that external execution.
