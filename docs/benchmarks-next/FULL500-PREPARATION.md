# Offline full500 preparation

This is preparation only: no hosted inference, no paid full500 dispatch, and no change to the live 50-query pilot, prompt v2 or its completion cap. The complete fixed 500-query TEST set produces 2,500 context rows and 7,500 planned requests across five arms and three repeats. No new query selection or label-based tuning is introduced.

The 50-query package measured 114,645,615 raw JSONL bytes and 11,780,394 gzip bytes. A tenfold estimate is about 1.146 GB raw and 117.8 MB compressed, so a single gzip can exceed GitHub's 100 MB file limit. The new helper streams batches of ten queries into deterministic gzip chunks, each containing at most64 MiB uncompressed data and required to remain below90 MiB compressed. No giant joined JSONL string or single large published file is necessary. Empty gzip filenames and `mtime=0` ensure stable compression metadata. The manifest records every chunk's raw/compressed hashes, byte and row counts, ordered reconstruction instructions, and the SHA of all concatenated original JSONL bytes. Guarded writes retain run provenance; no historical artifact is rewritten.

Reuse all 50 pilot A/C ranking traces exactly after verifying fixture, actual delivery-result, prompt, model snapshot and pilot raw-manifest hashes. Run the unchanged local MiniLM/MPS dense and cross-encoder pipeline only for the remaining450 questions. Preserve the original canonical candidate inventory, limits and ranking/serialization functions. For every one of the250 overlapping pilot rows, verify byte-for-byte serialized-row SHA equality against the frozen pilot; a difference stops preparation. All models are local-only, with unchanged snapshot hashes checked before and after preparation. No provider credential is read.

The package reports the actual conservative UTF8-byte-plus512 input reservation and maximum bound per arm. Keep input caps A/C/D/E8192 and B16384 for the estimate, explicitly flagging any rows that exceed them. Report completion1024 as the unchanged pilot option, and completion4096 as a **separate future option** motivated by observed transport `length` flags. This is not a silent pilot change or a decision to dispatch either full500 option. Their output reservations are7,680,000 and30,720,000 tokens respectively; costs remain unknown and no USD price is claimed. Input limits cannot be silently met by truncation.

```bash
# Run only after helper/source freeze in a clean isolated worktree.
python -m benchmarks.answer_full500 --results FROZEN_DELIVERY_RESULTS.json
```

The final `answer-full500/manifest.json` includes original pilot/reference hashes, exact overlap checks, model revisions, local/new versus reused query counts, all new rank traces, estimates and chunk storage provenance. To reconstruct a runnable JSONL file, decompress chunks in their listed order and concatenate their bytes, then verify the recorded full raw SHA before any future harness use.

## Verified preparation result

The frozen `cd4aee2` run produced2,500 rows for500 questions,1,150,218,330 raw bytes, and118,458,313 compressed bytes in18 chunks (largest6,924,158 bytes). All250 original pilot rows remain byte-identical. The independent streaming verifier reproduces the concatenated raw SHA `1dadbf17356fe4a58dd316f248993e2f21e5e6a70a11ba649d1aa62171afdfd6` and checks every input bound. No row exceeds A/C/D/E8192 or B16384. Conservative input reservation is67,633,470 tokens for7,500 requests; output options remain7,680,000 or30,720,000 tokens. No paid full500 run has started. [Manifest and estimates](answer-full500/manifest.json) · [Verification](answer-full500/verification.json).

The50 pilot questions belong to this same500-question set. A later full500 answer run must not be described as500 entirely new independent cases. Alongside the prespecified full-set result, report the450 nonpilot questions separately and disclose any completion-budget change motivated by the pilot's transport failures. This planned sensitivity view is not a replacement score or a basis for selecting favorable queries.
