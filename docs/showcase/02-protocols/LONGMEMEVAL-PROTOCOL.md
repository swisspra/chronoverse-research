# LongMemEval-S vanilla dense retrieval diagnostic

> **STATUS · PROTOCOL (frozen)** — original dated 2026-09-13 00:41 · chain and replacements in [`00-START-HERE/VERSION-MAP.md`](../00-START-HERE/VERSION-MAP.md)

Freeze this protocol and `benchmarks/longmemeval_rag.py` before running the full
500-question diagnostic. This is a local, gold-free context builder plus coarse
session-support scoring. It is not full Chronoverse lifecycle/receipt projection,
Graphiti, an official answer benchmark result, or a generated-answer experiment.

## Source and isolated scopes

Use the pinned cleaned LongMemEval-S file at Hugging Face revision
`98d7416c24c778c2fee6e6f3006e7a073259d48f`, source SHA-256
`d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`.
The existing preflight inventories 500 questions, 23,867 session instances and
246,750 turns. No external API is used.

Each question has an independent candidate ledger. Ingress whitelists question
text/date and each history session's ID/date/role/content. `answer`,
`answer_session_ids`, `has_answer`, and question ability labels never enter the
retrieval or model text. Session and question identifiers are metadata only.
Chunk IDs include question identity and session slot; duplicated source session
IDs cannot collide. Thirteen ledgers contain duplicate session IDs; none of
those duplicated IDs is a positive support ID in this pinned dataset.

## Frozen text, chunks and model

Each turn becomes the exact text `role: content`. Split using the pinned MiniLM
fast tokenizer's character offsets into nonoverlapping pieces containing at most
**256 model tokens including special tokens**. Re-tokenize every piece to verify
that bound. The concatenation of pieces exactly reproduces the original labeled
turn: no tail is discarded. The role is retained as metadata on every piece;
only the first piece contains the original role prefix. WordPiece boundaries can
split a word between pieces; this limitation is preferable to silently dropping
long-turn content and is not an optimized semantic chunker.

Use local SentenceTransformers MPS float32
`sentence-transformers/all-MiniLM-L6-v2`, model revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, maximum sequence length 256. Record hashes
of all snapshot files including pooling configuration. Questions exceeding 256
tokens use the model's configured truncation and are counted. No model, threshold,
chunk size or top-k is selected using answer labels.

Persistent derived vectors use the existing exact-cosine `VectorIndex` utility,
not `Store.query`. Keys contain model fingerprint and exact chunk-text SHA-256;
corrupt or incompatible rows are rebuilt by that utility. Sharing a vector for
identical text never shares candidate membership, session metadata or retrieval
results. Matrix work is bounded to 256 chunks; missing encoding batches are at
most 32. Query vectors are encoded fresh once per question.

## Two arms and context outputs

1. **dense**: exact cosine ranking of this question's history chunks only.
2. **dense_session_date_cutoff**: the same scoring, restricted to sessions whose
   supplied date is at or before the supplied question date, inclusive.

Session dates use the dataset's timezone-unspecified calendar clock. Do not infer
recording delays, valid-time revisions, recipient receipts, or a third-clock
benefit from them. Report how many future session instances the cutoff excludes;
if none exist, equivalence is a meaningful negative result.

Cosines are computed once per chunk and reused for the two ranking pools. This
is exact because cosine has no corpus-dependent component. Sort by unrounded
score, then opaque chunk ID for deterministic ties. Retain the top 10 and score
its top-5 and top-10 prefixes. There is no sufficiency threshold or answer model.

`contexts.jsonl` preserves exact selected texts, dates, source offsets, IDs and
scores for audit. Its separate **answerer_input** object contains only the
question/date and selected text/role/date with opaque citation/session keys.
A later answerer must receive that object, not the whole audit record: raw
question IDs can contain the `_abs` label and must not enter a model prompt.
Use identical top-k/context budgets and the same answerer across arms later.

## Session-support diagnostics, not passage recall

Only the scoring layer reads official `answer_session_ids`. Map them against the
question's own history session IDs, report unmapped labels, and exclude incomplete
mappings from positive recall. Compute distinct support-session recall and the
fraction with all support sessions represented at top 5 and 10, overall and by
official ability. Retrieving any chunk from a gold session counts as session
coverage even if that particular chunk does not contain the answer; therefore
these numbers are not answer-containing-passage recall or answer accuracy.

All **30 `_abs` questions retain nonempty related `answer_session_ids`**. Preserve
those annotations, but exclude these questions from positive support recall.
Report their empty-context rate separately; it does not establish correct answer
abstention without running an answerer. Do not relabel their retained sessions as
positive answer evidence or fabricate empty official annotations.

## Execution gates

```sh
PYTHONPATH="$PWD/backend:$PWD" .bench-mps-venv/bin/python -m benchmarks.longmemeval_rag --stage preflight
PYTHONPATH="$PWD/backend:$PWD" .bench-mps-venv/bin/python -m benchmarks.longmemeval_rag --stage run
```

Preflight tokenizes and inventories without loading/encoding the embedding model.
The full run should start only after code/protocol are committed; use a clean
isolated worktree and shared read-only model/data links. Derived SQLite vectors
live under ignored benchmark data, never a production profile. Result and context
writers use provenance guards. Preserve source hashes, model fingerprints, counts,
per-question diagnostics and exact context bytes. Shared-machine timing is
operational evidence, not a speed advantage claim.
