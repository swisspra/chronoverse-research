# Scaled delivery experiment v3

This protocol is implemented in `benchmarks/delivery_v3.py`. Freeze its source,
fixture and predictions commit before measurement. The fixture is generated and
reviewed separately; the retriever imports no reference or gold-authoring code.
Fixture gzip SHA-256 and decompressed JSON SHA-256 are both recorded. Default
selection is 108 DEV, 500 TEST and 50 historical compatibility requests. Report
these splits separately; DEV and TEST deliberately share parent mechanisms.

## Retrieval arms and item scope

Keep the original five assertion-context arms: global temporal, scalar clock,
filter after projection, ordinary SQL receipt filtering and delivery projection.
All inherit the actual current `Store.query`, with unchanged weights, threshold,
MiniLM model and top five limit. The sixth arm is separately labeled **Delivery
explicit item view**. Its additional candidates are received standalone evidence
and, for explicit notice wording, received lifecycle notices. It is a capability
extension, not an improvement silently applied to the five original arms.

Evidence items use parent world/plane/perspective and native half-open validity,
plus the passage's own source and receipt cutoffs. Parent recording time is not
an additional evidence gate: a source passage may enter the ledger before the
parent claim record. They do not inherit lifecycle retirement or
require parent receipt. Evidence already attached to an eligible assertion is
omitted as a duplicate candidate. No undelivered parent subject, object, summary
or replacement text enters item ranking or graph construction. Standalone item
text is constructed from the item's own source/title and passage/reason; its
status is `available_item`, not an active claim or endorsement.

The fixed notice intent vocabulary is `notice`, `notices`, `correction`,
`retraction`, `supersession`. It examines question words, never the query's gold
kind. Notice items require source/receipt cutoffs and parent dimensions; parent
validity and event effective time do not restrict notice availability. A notice
can describe a future change and includes its exact effective timestamp. This
follows `benchmarks/SPEC-TRI-TEMPORAL.md`.

## Measurement and support

Run two complete deterministic repetitions. Before each request clear the query
embedding LRU; document vectors remain persisted. One immutable isolated ledger
is shared by three adapter handles, and its exact-text vector rows are shared
across arms. The first repeat includes incremental preparation; later repeats
measure warm document retrieval plus fresh query encoding. Timings also include
candidate-signature instrumentation and shared-machine contention. They are not
independent cold index or uninstrumented production latency comparisons.

For each request record the exact returned top five contexts, scope, score
components, source passage/event identities, support matches, missing support,
and returned items violating receipt/source cutoffs. Full candidate projections
are hashed before ranking instead of serialized repeatedly. Repeated signatures
include returned text, scores, evidence, event state, graph, and candidate hash;
latency is excluded. Any repeated signature mismatch aborts completion with the
method and query identity. Compare SQL and delivery context signatures and projection
hashes. No thresholds or weights are selected using DEV or TEST labels.

An assertion support unit requires the relevant claim and its required passages.
Standalone gold passages remain answerable even without a parent claim. Gold
notices count as event support for explicit event-kind questions; missing notices
are false abstention, never correct empty-gold behavior. Historical event labels
were diagnostic annotations, so the compatibility query contract remains the
original assertion/evidence support contract. Report notice retrieval, standalone
evidence retrieval and correction claim support separately. The primary correction
family group is delayed_correction, delayed_retraction and historical_event_receipt,
excluding event-only questions. Planned paired comparisons use TEST queries in
these families; event-only notice support is a separate analysis. Empty denominators
are `null`; do not turn absent groups into apparent perfect performance.

Report overall, split, family, split-by-family and kind metrics. A query with no
gold support may still retrieve irrelevant received records: availability is
not relevance or answer sufficiency. Synthetic scenarios and repeated vocabulary
are not independent real-world observations. The new item view can also retrieve
retired-but-received source passages; record any precision cost transparently.

## Answer-experiment contexts

`retrieval-contexts.json` contains exact D (filter after projection) and E (delivery
with explicit item view) top-five contexts. B supplies all versions of the longest
unique corpus subject occurring in the question, using question and corpus text
only, without gold IDs or the fixture's entity annotation. No unambiguous subject
match gives an empty context and is recorded. A raw dense and C local reranker
contexts are explicitly pending until separately measured. Retrieval context
availability does not claim an answer-model experiment has run.

```sh
.bench-venv/bin/python -m benchmarks.delivery_v3 \
  --fixture benchmarks/data/delivery-v3.json.gz \
  --output-dir docs/benchmarks-delivery-v3
```

`--pilot-limit N` selects the first N DEV requests only, emits diagnostic timing
and stability but no aggregate support metrics, and labels its status
`pilot_unscored`. `--embedding-mode hashed` exists for fast integration tests;
those tests do not constitute the semantic benchmark. Normal results refuse a
dirty tree unless `--allow-dirty` is explicitly supplied.
