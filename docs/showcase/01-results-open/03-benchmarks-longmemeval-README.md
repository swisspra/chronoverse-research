# LongMemEval-S: local dense retrieval diagnostic

> **STATUS · CURRENT** — original dated 2026-09-13 01:25 · chain and replacements in [`00-START-HERE/VERSION-MAP.md`](../00-START-HERE/VERSION-MAP.md)

All 500 public question ledgers were processed locally using the frozen MiniLM protocol. Strict session-date filtering reduced coarse support-session recall; this experiment does not support claiming a temporal retrieval improvement. No answer model or external API was called.

## Overall result

Positive recall uses 470 answerable questions. The 30 `_abs` questions retain their official related-session annotations and are excluded from positive recall. Both arms returned nonempty contexts for all 30; answer abstention was not evaluated.

| Method | Session recall@5 | Session recall@10 | All support sessions@5 | All support sessions@10 |
|---|---:|---:|---:|---:|
| Dense | 79.82% | 90.01% | 65.11% | 81.28% |
| Dense + inclusive session-date cutoff | 75.22% | 84.48% | 60.00% | 74.26% |

A retrieved chunk counts if its session ID is in the official `answer_session_ids`. It need not contain the answer itself. These are **session-coverage diagnostics**, not passage recall, generated-answer accuracy, or official leaderboard scores.

## Per-ability session recall

| Official ability | Positive questions | Dense@5 | Cutoff@5 | Dense@10 | Cutoff@10 |
|---|---:|---:|---:|---:|---:|
| knowledge-update | 72 | 79.86% | 79.17% | 95.83% | 95.14% |
| multi-session | 121 | 70.22% | 70.22% | 84.37% | 84.37% |
| single-session-assistant | 56 | 100.00% | 100.00% | 100.00% | 100.00% |
| single-session-preference | 30 | 86.67% | 86.67% | 96.67% | 96.67% |
| single-session-user | 64 | 92.19% | 92.19% | 95.31% | 95.31% |
| temporal-reasoning | 127 | 72.19% | 55.58% | 83.44% | 63.36% |

## Read-only diagnosis after the frozen run

The strict minute-level cutoff excludes 1,475 session instances overall. Of the 470 positive questions, 41 lose at least one official support session: 40 temporal-reasoning questions and one knowledge-update question. This removes 70 question-local distinct support IDs (69 temporal-reasoning, one knowledge-update). All 70 have the same calendar date as the question but a later supplied time; none has a strictly later calendar date. Every question timestamp includes `HH:MM`, so absent time-of-day metadata is not established as the cause. The two top-10 outputs differ on 51 of 500 questions.

Public metadata examples (IDs and timestamps only):

| Question ID | Question timestamp | Support session ID | Session timestamp |
|---|---|---|---|
| `gpt4_2655b836` | `2023/04/10 (Mon) 10:15` | `answer_4be1b6b4_1` | `2023/04/10 (Mon) 10:57` |
| `gpt4_2655b836` | `2023/04/10 (Mon) 10:15` | `answer_4be1b6b4_2` | `2023/04/10 (Mon) 20:30` |
| `gpt4_2487a7cb` | `2023/05/24 (Wed) 08:02` | `answer_1c6b85ea_1` | `2023/05/24 (Wed) 16:55` |

Our strict minute-cutoff policy removes officially expected support. The question/session timestamps are not validated source-recording or receipt clocks, and this is not a claim that the dataset or its support labels are erroneous. It does not prove why the source metadata has that relationship. The baseline was not changed to day-level filtering, and no cutoff was tuned after reading labels. No valid-time, source-recording, recipient-receipt, lifecycle, or Graphiti behavior is being inferred. This result provides no evidence for or against actual Chronoverse lifecycle semantics.

## Reproducibility and reusable contexts

- Frozen retrieval commit: `543705a1f98cac69187c2906f525392eec424a8f`.
- Model: local MPS float32 `sentence-transformers/all-MiniLM-L6-v2`; exact model file hashes and runtime package freeze are retained in the result.
- Inventory: 23,867 session instances, 246,750 turns, 379,651 chunks, 289,526 unique exact texts. Each chunk is at most 256 model tokens including special tokens; lossless turn splitting discarded no tail. No question exceeded 256 tokens.
- Runtime: 1597.34 seconds on a shared machine. This includes tokenization, fresh question encoding, derived-vector reuse/encoding, and exact cosine work; it is not an isolated speed comparison.
- Question ledgers remain independent. The derived cache shares exact text vectors only. Gold answers, support IDs, `has_answer`, and ability labels never enter embeddings or candidate selection.
- `contexts.jsonl.gz` preserves exact selected chunks and audit metadata. Future answerers must consume only each row’s `answerer_input`, which excludes raw question/session IDs and labels. Keep the same answerer and context budget across arms.
- The original uncompressed outputs remain in the isolated run directory. Published gzip uses `mtime=0` and round-trips byte-for-byte. Packaging has separate provenance; measured artifacts retain their original provenance, including truthful generated-output dirty exemptions.

| Artifact | Uncompressed SHA-256 | Published gzip SHA-256 |
|---|---|---|
| [results.json.gz](results.json.gz) | `9559da5371b528699a30303cb22d557cde3c59f00d2727ae49e99ca05b5d25cc` | `26cf694e603b88da801334f003b483089d5cf0e63e2d2bfeecef994e8a0f577d` |
| [contexts.jsonl.gz](contexts.jsonl.gz) | `da592aca9c405390abd29f1c8da2106939e9e9d4060626da24e49de0d0a7e3f9` | `d06a3b9334204e272379bc4bb210cb262a06f6f5b8d04a6f13f8d1ea38e4387f` |

[Summary](summary.json) · [Protocol](PROTOCOL.md) · [Preflight](preflight.json)
