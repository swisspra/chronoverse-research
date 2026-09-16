# Five-arm answer harness — protocol v2

> **STATUS · PROTOCOL (frozen)** — original dated 2026-09-13 00:41 · chain and replacements in [`00-START-HERE/VERSION-MAP.md`](../00-START-HERE/VERSION-MAP.md)

This harness prepares, estimates or executes explicitly supplied OpenAI-compatible requests. Its default is `prepare`; neither `prepare` nor `estimate` reads an API credential or opens a network connection. Provider endpoint, model and key-file location are supplied at runtime and are not committed. No endpoint compatibility, model quality, paid execution or Batch availability is claimed by offline tests.

## Manifest and fixed inputs

The JSONL manifest has exactly one row per `(query_id, arm)` and all five arms A/B/C/D/E for every query. A 50-query pilot therefore has 250 manifest rows and **750 requests** across three repeats. Execution order is fixed by repeat, query ID, then A/B/C/D/E. The model is a required CLI argument; all arms use the same model, prompt, temperature 0, reasoning effort `low` and completion limit. Provider support for these fields must be verified before the real pilot; unsupported fields cause an error, not silent removal.

Each row contains:

```json
{
  "query_id": "q1", "arm": "E", "question": "What was reported?",
  "recipient_id": "recipient-red", "valid_at": "...", "known_at": "...", "received_by": "...",
  "context": [{"id": "assertion:example", "text": "A source passage"}],
  "prompt_sha256": "SHA256 of answer-prompt-v2.txt",
  "expected_answers": ["required value one", "required value two"],
  "gold_support_ids": ["assertion:example"], "visible_ids": ["assertion:example"], "stale_ids": [],
  "answerable": true, "family": "delayed_correction", "event_only": false
}
```

Only question, recipient/time coordinates, and context `{id,text}` pairs enter [the versioned prompt](answer-prompt-v2.txt). Expected answers, visibility, stale IDs, family and gold support are **scoring-only** metadata. All IDs use the same typed namespace (`assertion:`, `evidence:`, `event:`). The harness rejects duplicate context IDs, missing arms, duplicate rows or any prompt-hash mismatch. It never silently truncates a context or changes a prompt to fit a budget. The manifest generator, separately reviewed, establishes each arm's retrieval behavior; the transport does not infer or change it.

Version 2 is fixed before any paid answer pilot or TEST response inspection. It explicitly explains all three clocks in the same prompt for every arm: item and receipt-log recording cutoffs, independent item receipts, delivered lifecycle notices, validity boundaries, conflict preservation, and the distinction between a source passage and an endorsed assertion. B therefore receives the domain rules required to reason over its full history. Version 1 remains as an unused preparation snapshot; no paid results were produced with it.

## Fixed context assembly

`answer_contexts.py` selects 50 TEST queries by family-stratified round-robin sampling with seed 20260912 (all nine families), or the complete 500 TEST queries. It never uses gold to choose the pilot. Five rows are generated per selected query:

- A: local MiniLM dense retrieval over the full raw item inventory, without eligibility filters: assertion chunks containing their passages, independently rankable evidence passages, and independently rankable notice records. Return the top five units. Original text and time/receipt metadata are supplied. All item kinds available to E are candidates here too.
- B: match exactly one `Test monitoring station [0-9]+` name in the question, then include all original versions for that subject, their evidence, lifecycle notices and receipt metadata. Gold IDs and the fixture's entity annotation do not select these items. This arm deliberately gives the answerer history beyond the requested cutoffs and asks it to reason over explicit dates.
- C: retrieve the same A top-50 pool and reorder it with local `ms-marco-MiniLM-L6-v2`; return the first five. Dense inference is FP32 MPS with sequence limit 256; cross-encoder inference is FP32 MPS with limit 512. The two text-processing stages and their limits are recorded.
- D: use exactly the saved `Filter after projection` top-five rows from the completed scaled delivery run.
- E: use exactly the saved `Delivery explicit item view` top-five rows, including standalone evidence and notices.

Each assertion, passage and event receives a typed context ID. D/E serialization includes only fields/evidence/events actually returned; it never reattaches hidden children from the raw ledger. Their receipt annotations respect both receipt-log and delivery cutoffs. A/B/C retain all receipt metadata as part of their unfiltered-history input. Gold support, expected values, and citation visibility/staleness fields are added only after all contexts have been constructed. Staleness respects recipient-visible lifecycle events; an unreceived global correction cannot mark a legitimately held older report stale.

Candidate identities are unique typed IDs. Assertion-chunk text includes its passages; a passage is also independently rankable using its own text/title and parent subject/predicate, without inheriting the parent's object value. Notices use only their own recorded fields and reason, never an injected replacement claim's text. A and C select five units before flattening. Repeated context IDs (for example, a passage returned both alone and inside a parent chunk) collapse on first occurrence without backfilling another ranked unit. This overlapping representation is explicit, not five guaranteed distinct claims. Ties use typed ID order. Candidate construction never reads query gold or eligibility labels.

Frozen-pilot representation limitation: standalone passages serialize their own recorded-time and receipt metadata. Their inherited parent validity interval may be absent when the parent chunk is not selected. Consequently, sharing the raw candidate inventory does **not** guarantee identical information coverage or an equal opportunity to reconstruct all validity decisions from each retrieved context. Full-history B includes the parent versions and is an essential strong control. This limitation is disclosed without changing the running 750-request pipeline, prompt or contexts.

Before publishing JSONL, the builder rechecks fixture, retrieval-result and prompt hashes and the guarded run's source/runtime identity. `BenchmarkRun.write_bytes` atomically writes the exact JSONL bytes with an integrity receipt; the subsequent guarded sidecar write rechecks those bytes. The sidecar records the full candidate-unit counts, selection trace, source inputs and local model artifact hashes.

The JSONL has a sidecar manifest carrying provenance, SHA-256, selected query IDs/family counts, A/C candidate IDs and all arm context IDs. It is created from an actually completed retrieval artifact; a missing D/E result is an error rather than a substituted context.

## Reservation and cost

Require positive explicit per-request input and completion token limits. A/C/D/E have one shared input limit; B has a separately reported limit for its deliberately larger context. The fixed reservation estimates each prompt as its UTF-8 byte length plus 512 units for chat framing, and reserves the full `max_completion_tokens` for every request, including potential reasoning tokens. This is conservative for ordinary byte-based tokenizers but is not a certified exact bound for an unknown proxy tokenizer/protocol.

Before **any** network dispatch, the complete three-repeat reservation must fit both explicit cumulative input-token and output-token caps. Requests cannot borrow extra budget from presumed cheap prior calls. Report actual usage when returned; missing usage remains unknown. If provider-reported usage exceeds a request reservation, stop subsequent dispatch and block automatic resume. A misbehaving provider can exceed a requested limit on the already-dispatched request; this client cannot retroactively prevent that charge.

USD rates are optional configuration. With no verified/configured proxy prices, report token reservations and `usd_reservation: null`, never zero dollars. A rate-derived estimate is not a provider invoice. The parent must review the 50×5×3 estimate and its provider budget before dispatch. API keys are read only for `run`, never included in output, requests logs or error strings.

## Transport and checkpoints

Use synchronous requests with **one worker** to an explicitly configured `/chat/completions` endpoint. This is a documented deviation from the proposed Batch track: Batch support for the configured proxy has not been established. It is not a Batch price/latency comparison.

The checkpoint is exclusively locked for the entire run. Before dispatch, write and fsync a `pending` record. Request identity covers model/body, prompt/context, arm, repeat, endpoint, scoring metadata and harness source hash. A completed request is never sent again on resume. A timeout, disconnect, non-2xx response, invalid response or interrupted pending request is **uncertain** and blocks automatic retry: a request may have been charged even when the response was lost. The caller must reconcile it externally rather than creating a silent second charge. No hidden network retry exists.

Only `finish_reason == "stop"` is scored. Truncated, filtered or otherwise invalid completions retain raw output, usage and latency but are marked `truncated_or_invalid`, with no successful-answer score and no automatic retry. Report them separately as failed attempts; excluding them from an accuracy denominator would overstate quality. Final result artifacts carry `BenchmarkRun` provenance; source drift or unapproved dirty runs cannot publish a normal completed artifact.

The requested model alias is not proof of the answering model. Every response stores the provider's returned `model` identity; `--expected-response-model` can pin the preflight identity. Without that flag, the first valid returned identity becomes the run identity. A missing identity or a later mismatch preserves the raw response and usage, removes its score, and stops further dispatch. Such a checkpoint cannot resume automatically. Never pool silently routed fallback models or describe an unknown identity as an immutable model. The current proxy routing has not yet been approved for the paid pilot.

## Deterministic scoring and limitations

- Abstention must be exactly `INSUFFICIENT EVIDENCE`. Report correct abstention on unanswerable cases and false abstention on answerable cases separately.
- The expected-answer array is a **required set**, not alternatives. `answer_closed_form_match` requires every normalized expected string to appear with word boundaries in the answer sentence. Thus `2` does not match `12`; a sentence with units is permitted. This is literal closed-form matching, not semantic exact match: negation, contradictions, numeric unit conversion and free-form equivalence require separate blinded adjudication.
- Parse a final `CITATIONS: ["typed:id"]` line or a standalone JSON-array line. Malformed/missing citation syntax is recorded. Support recall requires all gold supports for full credit; missing or extra citations remain inspectable.
- Primary citation support uses preregistered equivalence groups: each required claim may be supported by its own eligible assertion ID **or** an explicitly gold supporting passage owned by that claim. A passage qualifies only with its own receipt within the delivery cutoff, item and receipt-log recording within the ledger cutoff, and no stale classification. It must also occur in the supplied context. Every required group must be satisfied; one source cannot substitute for an unrelated required claim. Orphan passages and event-only supports retain their own typed IDs and never resurrect or borrow a hidden parent. Strict typed-ID support remains a supplementary metric, and literal closed-form answer matching remains separate. These groups were specified before any paid answer response inspection.
- Report cited IDs absent from `visible_ids`, cited stale IDs, and cited IDs absent from the actual context separately. These are citation-level audits. Correct citations do **not** prove that the answer has no uncited semantic leakage or unsupported content.
- Keep event-only cases separate using the supplied flag and typed event IDs. Do not force an event-only answer to abstain merely because it has no assertion support.
- Report all three repeats, per-family outcomes, failed/truncated attempts and between-repeat variation. Temperature zero does not guarantee provider determinism. No official/public-answer benchmark or architectural superiority follows from this harness alone.

## Commands

```bash
# Offline preparation/estimate; use explicit bounds chosen for the manifest.
.bench-venv/bin/python -m benchmarks.answer_experiment --mode estimate \
  --manifest CONTEXTS.jsonl --model MODEL \
  --max-input-tokens INPUT_CAP --long-max-input-tokens B_CAP \
  --max-completion-tokens OUTPUT_CAP

# Runtime only, after the estimate and authorized budget are reviewed.
# Add --mode run, --base-url, --key-file, --max-total-input-tokens,
# --max-total-output-tokens and an isolated --checkpoint path.
```

Offline tests use a localhost fake HTTP server only: budget rejection before requests, prompt-hash mismatch, no gold ingress, 15 deterministic dispatch slots, deduplicated resume, uncertain-error refusal, truncation exclusion, provider budget-overrun stop, typed citations and required-set matching.
