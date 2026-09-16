# Which script is which

> **STATUS · CURRENT** — the script half of the version map. Documents and results are in
> [`00-START-HERE/VERSION-MAP.md`](../../00-START-HERE/VERSION-MAP.md); the whole round in order is
> in [`06-timeline/`](../../06-timeline).

File modification times are useless here: the 2026-09-13 folder consolidation rewrote absolute paths
in every script at once, so they all carry the same timestamp. Order them by what they produced.

| Script | Produces | Generation | Use it? |
| --- | --- | --- | --- |
| `extract.py` | `pe-asia-2025.jsonl` — text pulled from the source reports | one only | yes |
| `parse_prices.py` | `pe-asia-2025-prices.jsonl` — the price grid, mechanically parsed | current (full grade labels + the duplicate-series assertion) | yes |
| `build_questions.py` | `icis-questions.jsonl` — 598 candidates, 100 sampled, seed 20260913 | current | yes |
| `index_v2.py` | `chunks-v2.jsonl` — one chunk per assessment row plus narrative | current; replaced `index_corpus.py`, whose 1,400-character blocks cut the price grid | yes |
| `run_arms_v3.py` | `arm-results-v3.jsonl` — `static`, `postfilt`, `asof` | current for the three preregistered arms | yes |
| `run_arms_v4.py` | `arm-results-v4.jsonl` — `static_item`, `asof_item` | current, post-hoc arms | yes |
| `run_lightrag.py` | `lightrag-results-hybrid.jsonl` | current | yes |
| `score_v3.py` | three-arm table | superseded | no — it reads three arms and makes the newer ones look missing |
| `score_v4.py` | six-arm table, per-series counts, exact McNemar | **current, the only live scorer** | yes |

Not copied here, kept in `experiments/copus-pilot/` for the trail: `index_corpus.py`, `run_arms.py`
and `score_arms.py` (first-generation, 1,400-character chunking, results 25.0 / 25.0 / 33.0), and
`run_arms_v2.py` / `score_v2.py` (the run discarded because truncated grade labels collapsed three
injection series into one answer key).

Run everything from `/Users/swissp/SCGC/Chronoverse/experiments/copus-pilot`, not from this folder —
that is where the index, the embeddings and the LightRAG store live. These are reference copies.
