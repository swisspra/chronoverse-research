# Three-clock index and MCP migration design

The current application persists append-only assertions and lifecycle events in SQLite and stores exact vectors by model artifact identity and projected text. The recipient-delivery adapter remains an experiment. This design extends the storage boundary without changing ranking weights or treating a similarity score as truth.

## Records and text versions

Add an immutable `receipts` relation scoped by profile with `(recipient_id, item_type, item_id, received_at, recorded_at)` and a receipt identity. Index the recipient and both time coordinates. Receipts for assertions, passages and notices are separate. Add a profile ledger revision that increases transactionally when an assertion, passage, event or receipt is appended. Revision identifies source state; it does not replace historical coordinates.

A vector belongs to a text version, not just an assertion. Each version records a stable item identity, text hash, model artifact and tokenizer identity, dimensions, normalization, world/plane/perspective, valid interval and knowledge interval. Knowledge intervals are half-open ranges of ledger states where that exact text and evidence membership apply. Delivery changes the set of evidence attached to a claim, so a single universal knowledge interval cannot represent every recipient's text. Prefer independently indexed atomic passages and assertion text, then assemble the exact permitted context. If a composite projected text vector is cached, identify its exact ordered visible evidence and event IDs and projected status explicitly. Never reuse a global composite vector in a narrower recipient view.

## Query order and cache isolation

Resolve profile and recipient, source recording cutoff, receipt recording cutoff and delivery cutoff first. Apply only the delivered lifecycle events when computing active versions at valid_at. Then construct visible text, lexical candidates and scoped graph neighbors. Rank exact candidates and return provenance-bearing support. Filtering an already retired global candidate set cannot recover a claim removed by an undelivered notice.

The full query-result cache key contains profile ID, recipient ID, valid_at, known_at, received_by, world, plane, perspective, include_retired, item view, query text, limit, model/tokenizer identity, ranking configuration and ledger revision. Normalize equivalent timestamps before hashing. A cache hit must never widen scope. Atomic vector caching may omit recipient only when keyed by immutable exact text and its complete embedding configuration; eligibility still runs for each request. Cache negative results only with the same revision boundary. Receipt ingestion invalidates affected result caches even when assertion count is unchanged.

## Migration and verification

1. Add tables and indexes in a versioned, reversible schema migration; do not invent historical receipts. Existing profiles retain their explicit two-clock query mode until delivery data are supplied.
2. Expose a new recipient-scoped API/MCP query requiring recipient_id and all three coordinates. Keep a separate named global view so omission cannot accidentally mean unrestricted access. Return effective scope, ledger revision, item IDs, text-version IDs, applicable notices and support citations.
3. Backfill atomic vectors from immutable source text in bounded batches. Keep old vectors readable until new-index parity is verified. Do not fabricate a passage's recording time from a later import.
4. Validate exact output equality, old-version recovery, orphan evidence, standalone notices, profile/recipient isolation, receipt-log lag, inclusive cutoffs and exclusive validity ends. Replay the same query against a fixed revision and compare full payloads after restart.

A caller may ask `recipient_id=red`, `valid_at=...`, `known_at=...`, `received_by=...` with `item_view=assertions|evidence|notices`. Delivery is an availability model, not an authorization system by itself; product access controls must constrain which profile and recipient the caller may query.

## ANN and shared cache gates

Keep exact scoped search permanently. Adopt ANN only after a representative profile shows candidate vector scoring is the dominant measured latency and publish recall loss against exact search at several index/query settings. A fast approximate shortlist that silently removes the only received historical version fails the gate. Projection and lexical preprocessing should be profiled separately, with matched warm/cold conditions and output equality.

Redis is deferred until measured multi-worker reuse justifies it. If introduced, it uses the full result-cache key above, revision-aware invalidation and bounded retention. SQLite vector persistence remains sufficient for a single local worker. No index, Redis service or production MCP behavior changes are made by this design document.
