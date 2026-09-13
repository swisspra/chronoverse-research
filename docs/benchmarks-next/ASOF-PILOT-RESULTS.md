# As-of pilot on a licensed real-world corpus

The delivery fixture is synthetic and authored in this repository. This pilot repeats the
knowledge-time half of the question on a third-party commercial corpus that this team licenses in
full: 55 weekly chemical market-price reports covering one product family across 2025, roughly
134,000 tokens of text.

**The corpus and everything derived from it stay out of this repository.** No report text, no price
table and no answer is published here; `.gitignore` excludes the working directory and any path
matching the vendor's name. What follows is method and measurement only. All inference ran through
the organisation's internal LLM proxy; no licensed content was sent to any external provider.

## Why this corpus tests the theory

Each issue states its own knowledge cutoff — the text says, in so many words, that the analysis
published on a given date carries information collected up to the day before. An assessment for a
week therefore exists only from the issue that published it. Asking *"as of date D, what is the most
recent assessment for series S"* has exactly one defensible answer, and every later issue in the
index is a future leak.

Gold comes from the price grid inside the reports, parsed mechanically: 660 assessment rows across
51 issues and 14 distinct series. No model judged any answer key.

Checked before use: the corpus contains **no retroactive revisions**. Comparing each issue's
four-week-lookback column against the value that issue actually published four weeks earlier gives
460 agreements and 0 disagreements. So this pilot tests knowledge time and future leakage; it cannot
test correction recovery, which remains the synthetic fixture's job.

## Arms

All three share one index, one embedding model, one answerer, one prompt, temperature 0. Only the
retrieval policy differs.

| Arm | Policy |
| --- | --- |
| `static` | one index over every issue, no time awareness — how a conventional RAG or graph index behaves |
| `postfilt` | retrieve top-k from the whole index, then drop chunks published after the asked date |
| `asof` | restrict the candidate pool to issues published by the asked date, then retrieve |

## Results, 100 questions

| Arm | Correct | Answered with a value from a later issue | Abstained | Context contained a future issue |
| --- | ---: | ---: | ---: | ---: |
| `static` | 77.0% | 0% | 2.0% | **90%** |
| `postfilt` | 77.0% | 0% | 2.0% | 0% |
| **`asof`** | **90.0%** | 0% | 0% | 0% |

Per series, `asof` is never behind:

| Series (n) | static | postfilt | asof |
| --- | ---: | ---: | ---: |
| HDPE film, China (13) | 12 | 12 | 12 |
| LDPE film, Vietnam all origins (11) | 8 | 8 | **11** |
| HDPE injection MFI>10, China (10) | 6 | 6 | **8** |
| HDPE blow moulding, Vietnam (9) | 5 | 5 | **6** |
| HDPE injection, China (9) | 7 | 7 | **9** |
| LDPE film, SE Asia dutiable (9) | 9 | 9 | 9 |
| LLDPE film, China (9) | 8 | 8 | **9** |
| LLDPE film, SE Asia dutiable (9) | 4 | 4 | **5** |
| HDPE injection MFI≤10 (7) | 7 | 7 | 7 |
| HDPE blow moulding, China (5) | 4 | 4 | **5** |
| LDPE film, SE Asia all origins (5) | 3 | 3 | **5** |
| LDPE film, China (4) | 4 | 4 | 4 |

## What the mechanism turns out to be

`static` and `postfilt` score identically, 77.0% each, even though `postfilt` never lets a future
issue into the context. Removing the future after retrieval changed no answers. The entire 13-point
gain belongs to `asof`, which spends its candidate budget only on issues that existed at the asked
date and therefore retrieves the right week in the first place.

So on real data the advantage is not "hiding the future from the model". It is **allocating
retrieval to the eligible corpus**. A conventional index spends its top-k on whichever week is most
similar in wording, and on a weekly series where every issue looks alike, that is usually the wrong
week — filtering afterwards cannot recover the right one because it was never retrieved. This is the
same filter-order result the synthetic fixture produced, arriving here through a different failure
mode and on a corpus nobody in this team wrote.

## A benchmark bug found and fixed during the run

The first scored pass showed one series at 0 out of 10 for every arm. It was not a retrieval failure:
the report publishes three distinct injection-grade series whose names share a prefix, and the parser
truncated grade labels to three words, collapsing all three into one key. The answer key then held
whichever price was written last, so no system could be right.

Fixed by keeping full grade labels, adding an assertion that fails the build if one series carries
two different prices in the same issue, and regenerating the question set — 598 candidate questions
over 14 series, 100 sampled with seed 20260913. The affected run was discarded rather than reported.

## Chunking, and why the first numbers were meaningless

The first index split each issue into 1,400-character blocks, which cut the price grid mid-table.
Everything scored badly: static 25.0%, postfilt 25.0%, asof 33.0%. The second index gives each parsed
assessment row its own short self-describing chunk carrying the publication date, and keeps prose
separately: 970 chunks, 660 assessments plus 310 narrative. All arms share it, so the change is
neutral between them — and it moved every arm at once, which is what a neutral change should do.

Any comparison against a third-party system has to declare its chunking. On this corpus, chunking
was worth more than the retrieval policy.

## Limits

One product family, one year, one answerer, one repeat, 100 questions. The corpus has no corrections,
so the delivery clock is not exercised at all. Licensed content cannot be redistributed, so an
external reader cannot rerun this without their own subscription. The next step is to put LightRAG,
Graphiti and Microsoft GraphRAG on this same index and question set, which is now clean enough to
make that comparison meaningful.
