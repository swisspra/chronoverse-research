# Delivery terminology migration

WI-03 and WI-04 rename the active receipt experiment and distinguish repository verification from the user-provided external review. Baseline Git tag `round-3-as-published` identifies the original published snapshot, commit `1154cf7`.

Active modules, tests, report and schema now use `DeliveryStore`, `recipient_id`, `received_by` and the `delivery` strategy. Receipt rows retain `received_at`. The [migration manifest](migration-manifest.json) records exact old/new result and fixture hashes. This is a schema migration, not a new inference run. Original metrics, candidate projections, scores, timings, ranking text and historical execution hashes are preserved.

## Historical exceptions

The original `docs/benchmarks-observer/` raw results, fixture, verification, screenshots and executed source archive remain unchanged. Its `index.html` redirects to the active delivery report. The old frozen `benchmarks/data/observer-v1.json` and draft remain unchanged. The renamed fixture generator explicitly translates the old schema from that frozen fixture; it does not regenerate gold from retrieval output.

Historical code, metadata, receipts, protocol descriptions and ranking inputs can retain `observer`, `quantum`, `collapse` or other original vocabulary. In particular, the literal passage marker and the bridge-collapse scenario are part of evaluated ranking text. Rewriting these to satisfy a text search would change experimental inputs or destroy provenance. These retained artifacts are excluded from the active-name cleanup.

The migrated result's `source_sha256` values still identify the historical archive. They do not attest that renamed active code produced the historical run. The verifier checks archived execution hashes and migration equality; future inference runs must record their own provenance.
