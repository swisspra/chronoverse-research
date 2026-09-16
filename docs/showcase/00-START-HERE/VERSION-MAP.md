# Version map — what is current, what is superseded, what was discarded

Built 2026-09-14. Every date below comes from a commit timestamp or from the artifact the run
actually wrote, not from guesswork.

**Read the mtimes with suspicion.** Every `*.py` in the pilot folder shows the same modification
time, `2026-09-13 01:25:34`, because the folder consolidation rewrote absolute paths in all of them
at once. File dates tell you nothing about which script came first. The chains below do.

---

## 1. The as-of pilot on the licensed corpus — four generations in one evening

| When | Generation | What changed | Result | Status |
| --- | --- | --- | --- | --- |
| 09-13 19:30 | `index_corpus.py` → `chunks.jsonl`, `run_arms.py` → `arm-results-v1-chunking.jsonl` | first index: 1,400-character blocks | static 25.0 / postfilt 25.0 / asof 33.0 | **superseded** — the blocks cut the price grid mid-table, so every arm was starved equally |
| 09-13 22:11 | `index_v2.py` → `chunks-v2.jsonl`, `run_arms_v2.py` → `arm-results-v2-partial-ambiguous.jsonl` | one chunk per assessment row | never reported | **discarded** — grade labels truncated to three words collapsed three injection series into one key, making that series unanswerable (0/10 for every arm) |
| 09-13 22:32 | `run_arms_v3.py` → `arm-results-v3.jsonl`, `score_v3.py` | full grade labels, assertion that fails on two prices in one series+issue, questions regenerated (598 candidates, 100 sampled, seed 20260913) | static 77.0 / postfilt 77.0 / asof 90.0 | **current** for the three preregistered arms |
| 09-13 23:42 | `run_arms_v4.py` → `arm-results-v4.jsonl` | adds `static_item` and `asof_item` | 6.0 / 100.0 | **current**, post-hoc — see the disclosure in `ASOF-PILOT-RESULTS.md` |
| 09-14 00:41 | `run_lightrag.py` → `lightrag-results-hybrid.jsonl` | LightRAG 1.5.7, own graph and chunking | 28.0 | **current**, with the chunking caveat |

**Scorers follow the same chain and only the last one is live:**
`score_arms.py` (v1) → `score_v2.py` (discarded run) → `score_v3.py` (three arms) →
**`score_v4.py` (six arms, exact McNemar — the only one to run today)**.

`score_v3.py` still works but reads three arms only; running it will look like the newer arms
vanished. Use `score_v4.py`.

**Question sets:** `icis-questions.jsonl` was regenerated at 09-13 22:11 and is the only version on
disk. Any result older than that timestamp — the v1 and v2 runs — was scored against a *different*
question set and cannot be compared line-by-line with v3/v4/LightRAG.

---

## 2. The answer experiment on the synthetic fixture — two rounds

| When | Generation | What changed | Status |
| --- | --- | --- | --- |
| 09-13 02:36 | `ANSWER-RESULTS.md`, arms A–E, 50 questions × 3 repeats, 1,024-token budget | the original pilot; stopped at 647 of 750 slots, then a frozen amendment finished the remaining 103 | **superseded on the headline, still valid as a record.** Its vanilla arm ranked with bare cosine and scored 12.0%; the margin it reported was mostly retrieval quality, not temporal semantics |
| 09-13 02:03–02:33 | `ANSWER-CONTINUATION-AMENDMENT.md` + audit | permitted only never-dispatched slots; one timeout stayed an unknown and counts as a failure | **current** as the amendment record |
| 09-13 19:27 | `ROUND2-ANSWER-RESULTS.md`, arms A2/B/C2/D/D2/E/Z, 4,096-token budget, three answerers | fixes both confounds: lexical+dense baselines, and a completion budget that removes truncation | **current** for the synthetic fixture |

Round 2 is the one to quote. Round 1 is kept because the correction is part of the evidence trail,
and `00-benchmarks-next-README.md` states it in the kill-criteria section.

---

## 3. Everything else, by date

| Date | Artifact | Status |
| --- | --- | --- |
| 09-12 | `PREDICTIONS.md`, `FANTOM-PROTOCOL.md`, `THREE-CLOCK-INDEX.md`, observer-round README | **current** — preregistration and design, not results |
| 09-13 00:59 | `OPENROUTER-RERANK-RESULTS.md` — SciFact 300 queries, nDCG@10 77.37% vs local cross-encoder 68.86% | **current** |
| 09-13 01:03 | `HOSTED-RESULTS.md` — SciFact 78.10 / NFCorpus 41.93 / FiQA 54.85 nDCG@10 | **current** |
| 09-13 01:53 | `ROUND-CLOSEOUT.md` — 20-item acceptance audit | **current** for that round; predates everything from 19:00 onward |
| 09-13 02:13 | `GRAPHITI-HEAD-TO-HEAD.md` — native Graphiti 0.30.2 + Neo4j, shared graph 96/175 (54.9%) vs per-recipient `group_id` 117/175 (66.9%), McNemar p = 0.033 | **current**, separate track from the pilot |
| 09-13 23:23 | `ASOF-PILOT-RESULTS.md` first version — three arms | **superseded within the same file** |
| 09-13 23:46 | same file, +`static_item` +`asof_item` | superseded within the same file |
| 09-14 00:43 | same file, +LightRAG — **the version copied here** | **current** |
| 09-14 01:30 | `.gitignore` hardening, folder consolidation | **current** |

`CHRONOVERSE-REVIEW-AND-NEXT-ROUND.md` (09-12 23:13) is the proposal that opened the round —
WI-01…WI-20. It is a plan, not a result: check each item against the status table in
`01-results-open/00-benchmarks-next-README.md` before assuming any part of it was done.

---

## 4. If you only trust five files

1. `00-START-HERE/SIX-ARM-SCOREBOARD.txt` — regenerated from raw answers, newest possible
2. `01-results-open/ASOF-PILOT-RESULTS.md` — real corpus, six arms, all caveats
3. `01-results-open/ROUND2-ANSWER-RESULTS.md` — synthetic fixture, current round
4. `03-reviews-and-proposals/GRAPHITI-HEAD-TO-HEAD.md` — the only native-competitor graph result
5. `01-results-open/00-benchmarks-next-README.md` — what the team itself claims is done, but it
   stopped at 09-13 23:23 and knows nothing about the item arms or LightRAG

Everything else is either a protocol (design, not evidence), a preparation note, or a superseded
generation kept for the trail.

---

## 5. Timeline folder

`../06-timeline/` holds every document and every answer file again as a date-prefixed symlink — 38
entries, so `ls` alone answers "which came first". The date in each name is the original file's last
commit (or, for the two review documents, the mtime of the source in `~/Desktop/Claude/Temp/`), not
the copy's mtime. `SUPERSEDED-` and `STALE-` mark generations something later replaced or overtook;
the target file itself is unchanged.

---

## 6. Status banner in every document

Every `.md` in `01-results-open/`, `02-protocols/` and `03-reviews-and-proposals/` now carries one
line directly under its title, so the age of a file is visible without coming back here:

```
> **STATUS · CURRENT** — original dated 2026-09-14 00:43 · chain and replacements in …
```

| Label | Means |
| --- | --- |
| `CURRENT` | nothing on disk replaces it |
| `SUPERSEDED` | a later generation replaced it; the note names the replacement |
| `STALE` | not replaced, but written before results it does not mention — read the note |
| `PROTOCOL (frozen)` | design, not evidence; a protocol is never "old", but the run it describes may not exist |
| `PROPOSAL` | a plan; check each item against the status board before assuming it was done |

Only one file carries `SUPERSEDED` (`ANSWER-RESULTS.md`) and only one carries `STALE`
(`00-benchmarks-next-README.md`, written 09-13 23:23 — before the item arms, LightRAG and the final
six-arm revision, none of which it mentions). Everything else in `01-` is current as of 09-14 02:00.

The banners were stamped mechanically from the table in §7; the stamper is idempotent and lives at
`~/Desktop/Claude/Temp/stamp_status.py`. Rerunning it after adding a document adds only the missing
banners.

---

## 7. Per-file status index — all 32 documents

| Origin date | File | Status |
| --- | --- | --- |
| 09-12 23:13 | `03-…/CHRONOVERSE-REVIEW-AND-NEXT-ROUND.md` | PROPOSAL |
| 09-12 23:21 | `02-…/OBSERVER-PROTOCOL.md`, `OBSERVER-VERIFICATION.md` | PROTOCOL |
| 09-12 23:21 | `01-…/04-benchmarks-observer-README.md` | CURRENT |
| 09-12 23:25 | `01-…/PREDICTIONS.md` | CURRENT (preregistration) |
| 09-12 23:34 | `01-…/THREE-CLOCK-INDEX.md` | CURRENT (design) |
| 09-12 23:37 | `02-…/FANTOM-PROTOCOL.md` | PROTOCOL |
| 09-12 23:48 | `02-…/DELIVERY-V3-PROTOCOL.md` | PROTOCOL |
| 09-13 00:03 | `02-…/SUFFICIENCY-PROTOCOL.md` | PROTOCOL |
| 09-13 00:26 | `01-…/02-benchmarks-delivery-v3-README.md` | CURRENT |
| 09-13 00:32 | `02-…/HOSTED-PROTOCOL.md` | PROTOCOL |
| 09-13 00:41 | `02-…/ANSWER-PROTOCOL.md`, `LONGMEMEVAL-PROTOCOL.md` | PROTOCOL |
| 09-13 00:50 | `02-…/OPENROUTER-RERANK-PROTOCOL.md` | PROTOCOL |
| 09-13 00:53 | `02-…/ANSWER-STATISTICS-PROTOCOL.md` | PROTOCOL |
| 09-13 00:53 | `01-…/01-benchmarks-v3-README.md`, `05-benchmarks-v2-README.md` | CURRENT |
| 09-13 00:59 | `01-…/OPENROUTER-RERANK-RESULTS.md`, `PROXY-CAPABILITIES.md` | CURRENT |
| 09-13 01:00 | `02-…/CLOCK-ABLATION-PROTOCOL.md` | PROTOCOL — the ablation has not been run |
| 09-13 01:03 | `01-…/HOSTED-RESULTS.md` | CURRENT |
| 09-13 01:11 | `01-…/FULL500-PREPARATION.md` | CURRENT (preparation; run still open) |
| 09-13 01:25 | `01-…/STUDY-BRIEF.md`, `03-benchmarks-longmemeval-README.md` | CURRENT |
| 09-13 01:27 | `01-…/GRAPHITI-NATIVE-PREFLIGHT.md` | CURRENT (preflight; run still open) |
| 09-13 01:53 | `01-…/ROUND-CLOSEOUT.md` | CURRENT for that round; predates 19:00 onward |
| 09-13 02:03 | `01-…/ANSWER-CONTINUATION-AMENDMENT.md` | CURRENT (amendment record) |
| 09-13 02:13 | `03-…/GRAPHITI-HEAD-TO-HEAD.md` | CURRENT (separate track) |
| 09-13 02:36 | `01-…/ANSWER-RESULTS.md` | **SUPERSEDED** by ROUND2 |
| 09-13 19:27 | `01-…/ROUND2-ANSWER-RESULTS.md` | CURRENT (synthetic fixture) |
| 09-13 23:23 | `01-…/00-benchmarks-next-README.md` | **STALE** — one generation behind |
| 09-14 00:43 | `01-…/ASOF-PILOT-RESULTS.md` | CURRENT — the headline |
| 09-14 02:00 | `00-START-HERE/SIX-ARM-SCOREBOARD.txt` | CURRENT — regenerated from raw answers |
| 09-14 02:15 | `00-START-HERE/COMPETITOR-ACCURACY.md` | CURRENT — every competitor comparison in one page, assembled from the documents above; no new measurement |
| 09-14 02:30 | `00-START-HERE/COMPETITOR-ACCURACY-TH.md` | CURRENT — Thai edition of the same page, plus concepts and step-by-step; same figures, no new measurement |
| 09-14 02:45 | `00-START-HERE/COMPETITOR-ACCURACY-TH.html` | CURRENT — the Thai edition rendered as a standalone HTML sheet; same figures again, edit the `.md` first and keep the two in step |
| 09-14 14:10 | `00-START-HERE/ACCURACY-LATEST.html` | CURRENT — one-page cover for handing the result to the team: which of the three summaries is current, the number chain, and the two caveats. A pointer, not a source |

Scripts are not in this table: they have their own chain in
`../04-licensed-DO-NOT-SHARE/scripts/LINEAGE.md`, and their file dates are meaningless for the
reason given at the top of this document.
