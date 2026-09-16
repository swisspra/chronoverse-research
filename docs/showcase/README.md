# Showcase copy — unverified working set

Everything this project produced that summarises a test, a result or a proposal, gathered in one
place on 2026-09-13. **These are copies.** The originals stay where they live; editing a file here
changes nothing upstream. Where a file came from is recorded in the tables below.

"Unverify" in the folder name is accurate and worth keeping: the copies were not re-checked against
their sources after copying, and several of the documents themselves describe results the team has
labelled provisional. Treat this folder as a reading pile, not as the record.

## Read this first

| File | What it is |
| --- | --- |
| `00-START-HERE/VERSION-MAP.md` | **Which file is current, which is superseded, which was discarded** — the four generations of the pilot in one evening, the scorer chain, and a per-file status index. Start here if anything looks like it might be out of date |
| `00-START-HERE/ACCURACY-LATEST.html` | **Hand this to someone first** — a one-page cover: which accuracy summary is current, where the numbers came from, and the two caveats that must travel with them |
| `00-START-HERE/COMPETITOR-ACCURACY.md` | **Chronoverse against everything else in one page** — LightRAG head-to-head, long context, Graphiti, hosted embeddings and rerank, cost, and the list of systems nobody has run yet |
| `00-START-HERE/COMPETITOR-ACCURACY-TH.md` | The same page in Thai, written for someone new to the project: the four ideas behind the method, the five answering steps, the six measurement steps, then the same tables |
| `00-START-HERE/COMPETITOR-ACCURACY-TH.html` | The Thai page as a self-contained HTML sheet — opens in a browser, prints cleanly, no build step and no local assets |
| `00-START-HERE/SIX-ARM-SCOREBOARD.txt` | The current six-arm table, regenerated from the raw answers at copy time, with per-series counts and exact McNemar p-values |
| `01-results-open/ASOF-PILOT-RESULTS.md` | The headline document: the as-of pilot on the licensed corpus, all six arms, mechanism analysis, disclosures |
| `01-results-open/00-benchmarks-next-README.md` | The team's own status board — every work item WI-01…WI-20 with its evidence and limits. Written 09-13 23:23, so it is one generation behind: no item arms, no LightRAG |
| `03-reviews-and-proposals/CHRONOVERSE-REVIEW-AND-NEXT-ROUND.md` | The 744-line review and execution proposal that opened this round |

## How to tell old from new

Every file here was copied at the same minute, so **file dates in this folder mean nothing**. Three
things carry the real order instead:

1. **A status banner under the title of every document** — `CURRENT`, `SUPERSEDED`, `STALE`,
   `PROTOCOL (frozen)` or `PROPOSAL`, with the original's date and, where it matters, what replaced
   it. Open any file and the first line after the title tells you where it stands.
2. **`00-START-HERE/VERSION-MAP.md`** — the chains: four generations of the pilot in one evening,
   which question set each was scored against, which scorer is still live, and a per-file index.
3. **`06-timeline/`** — all 38 documents and answer files again as date-prefixed symlinks, so `ls`
   alone answers "which came first". `SUPERSEDED-` and `STALE-` appear in the names.

For the pilot scripts, the equivalent is
`04-licensed-DO-NOT-SHARE/scripts/LINEAGE.md` — order them by what they produced, never by mtime.
Two traps it records: `score_v3.py` still runs but reads three arms only, so the newer arms look
missing; and any result older than 09-13 22:11 was scored against a different question set.

The full session handoff (folder layout, environment traps, next steps in order) is saved in the
Chronoverse project on claude.ai as `claude/handoff-2026-09-13.md`, and was also delivered into the
chat as a file.

## The current numbers, so you do not have to open anything

100 questions, one corpus, one answerer (`vertex_ai/gemini-3.8-flash`), temperature 0, top-k 8.
Only the retrieval policy changes between arms.

| Arm | What it does | Correct |
| --- | --- | ---: |
| `lightrag_hybrid` | LightRAG 1.5.7, its own graph and chunking, no knowledge-time projection | 28.0% |
| `static` | one index over everything, no time awareness | 77.0% |
| `postfilt` | retrieve first, then drop future issues | 77.0% |
| `asof` | restrict to issues known at the asked date, then retrieve | 90.0% |
| `static_item` | latest version per series over the whole corpus, no time awareness | 6.0% |
| **`asof_item`** | **known issues, then latest version per series** | **100.0%** |

Three findings, in order of how well they hold: post-filtering is worth exactly nothing (`static`
and `postfilt` differ on zero questions); the clock and the item view only work composed (the item
view alone scores 6.0% and abstains 92% of the time); and LightRAG cannot use a date handed to it in
the question text, losing 72 questions to `asof_item` and winning none.

Both item arms are **post-hoc** on this sample, and every question aggregates along the same axis the
item view collapses — so the 100% means "retrieval was the whole bottleneck on this question form",
not a general accuracy claim. `ASOF-PILOT-RESULTS.md` states both caveats in full.

## What is in each folder

| Folder | Contents | Source | Safe to share |
| --- | --- | --- | --- |
| `00-START-HERE/` | regenerated scoreboard + `VERSION-MAP.md` | computed at copy time | figures only — yes |
| `01-results-open/` | 19 result and status documents | `repo-private/docs/**`, `PREDICTIONS.md` | yes — these are committed to Git, public snapshot included |
| `02-protocols/` | 11 frozen protocols and verification records | `repo-private/docs/**` | yes |
| `03-reviews-and-proposals/` | the review proposal and the Graphiti head-to-head | `~/Desktop/Claude/Temp/` | yes |
| `04-licensed-DO-NOT-SHARE/` | pilot scripts, questions, parsed prices, every model answer | `experiments/copus-pilot/` | **no — see below** |
| `05-architecture-html/` | 7 architecture and business HTMLs | `docs-private/`, `prototype-graphrag/` | internal only |
| `06-timeline/` | 38 date-prefixed symlinks — the whole round in order | links into the folders above | follows the target: five links point into `04-` |

## The one hard rule

`04-licensed-DO-NOT-SHARE/` contains material derived from a third-party commercial corpus. The
licence is paid in full and permits use; it does **not** permit redistribution. That folder holds
parsed price values, the question set built from them and every model answer, so it must not be
committed to Git, attached to an email outside the team, uploaded to a vendor service, or included
in anything published. The raw report text was deliberately *not* copied here — it stays in
`experiments/copus-pilot/pe-asia-2025.jsonl` and `experiments/COPUS-TESTSET/`.

Everything in `01-` through `03-` was written to be publishable: method, counts and percentages, no
report text, no price table, no model answer. That is why `ASOF-PILOT-RESULTS.md` can sit in both
categories — the document is safe, the data behind it is not.

## Inventory

`01-results-open/` — ASOF-PILOT-RESULTS · ROUND2-ANSWER-RESULTS · ANSWER-RESULTS ·
ANSWER-CONTINUATION-AMENDMENT · HOSTED-RESULTS · OPENROUTER-RERANK-RESULTS · ROUND-CLOSEOUT ·
GRAPHITI-NATIVE-PREFLIGHT · THREE-CLOCK-INDEX · FULL500-PREPARATION · PROXY-CAPABILITIES ·
PREDICTIONS · STUDY-BRIEF · and six benchmark-round READMEs numbered `00-` to `05-`
(next, v3, delivery-v3, longmemeval, observer, v2).

`02-protocols/` — ANSWER · ANSWER-STATISTICS · FANTOM · CLOCK-ABLATION · SUFFICIENCY · HOSTED ·
OPENROUTER-RERANK · DELIVERY-V3 · LONGMEMEVAL · OBSERVER-PROTOCOL · OBSERVER-VERIFICATION.

`04-licensed-DO-NOT-SHARE/scripts/` — extract · parse_prices · build_questions · index_v2 ·
run_arms_v3 · run_arms_v4 · run_lightrag · score_v3 · score_v4.
`04-licensed-DO-NOT-SHARE/data/` — icis-questions · pe-asia-2025-prices · arm-results-v3 ·
arm-results-v4 · lightrag-results-hybrid · the two run logs · lightrag-ingested.

To regenerate the scoreboard after any new run:
`cd ../experiments/copus-pilot && uv run --with numpy python score_v4.py --mcnemar`
