# Licensed material — do not redistribute

Everything in this folder is derived from a third-party commercial market-report corpus. The team's
licence is paid in full and permits internal use. It does **not** permit redistribution.

**Never:** commit any of this to Git, send it outside the team, upload it to a vendor API or public
service, or include it in a published document or paper appendix.

**Fine:** read it, rerun the scripts against the local corpus, and publish the *measurements* —
counts, percentages, p-values, method descriptions. That is exactly what the documents in
`../01-results-open/` do.

## What is here

| File | Licensed content it carries |
| --- | --- |
| `data/pe-asia-2025-prices.jsonl` | every parsed price assessment — the vendor's actual numbers |
| `data/icis-questions.jsonl` | 100 questions plus their gold answers, which are those prices |
| `data/arm-results-v3.jsonl` | 300 model answers quoting those prices |
| `data/arm-results-v4.jsonl` | 200 model answers, the two item arms |
| `data/lightrag-results-hybrid.jsonl` | 100 LightRAG answers |
| `data/arms-v3.log`, `data/arms-v4.log` | run logs — token counts and timings, no prices |
| `data/lightrag-ingested.json` | index build cost record, no prices |
| `scripts/*.py` | no licensed content, but every path points at it |

The raw report text is **not** in this folder by design. It lives in
`../../experiments/copus-pilot/pe-asia-2025.jsonl` (extracted text) and
`../../experiments/COPUS-TESTSET/` (the source files, ~6 GB).

## Running anything here

The scripts in `scripts/` are copies and their paths point back at
`/Users/swissp/SCGC/Chronoverse/experiments/copus-pilot`, which is where they should actually be run
from — that folder has the index, the embeddings and the LightRAG store. Run them there, not here.

All inference goes through the internal proxy only (`https://scgc-llmproxy.scg.com/v1`). No licensed
text has ever been sent to an external provider, and nothing here should change that.
