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

All five share one index, one embedding model, one answerer, one prompt, temperature 0, top-k 8.
Only the retrieval policy differs.

| Arm | Policy |
| --- | --- |
| `static` | one index over every issue, no time awareness — how a conventional RAG or graph index behaves |
| `postfilt` | retrieve top-k from the whole index, then drop chunks published after the asked date |
| `asof` | restrict the candidate pool to issues published by the asked date, then retrieve |
| `static_item` | collapse each series to its latest version in the **whole** corpus, then retrieve |
| `asof_item` | restrict to issues published by the asked date, **then** collapse each series to its latest version inside that eligible set, then retrieve |

The first three were fixed before any answer was generated. The two item arms were added afterwards,
once the failures of `asof` had been read; see the disclosure below.

## Results, 100 questions

| Arm | Correct | Gold issue in context | Answered with a value from a later issue | Abstained | Context contained a future issue |
| --- | ---: | ---: | ---: | ---: | ---: |
| `static` | 77.0% | 79.0% | 0% | 2.0% | **90%** |
| `postfilt` | 77.0% | 79.0% | 0% | 2.0% | 0% |
| `asof` | 90.0% | 92.0% | 0% | 0% | 0% |
| `static_item` | 6.0% | 11.0% | 0% | **92.0%** | **97%** |
| **`asof_item`** | **100.0%** | **100.0%** | 0% | 0% | 0% |

Exact McNemar, two-sided, paired on the same 100 questions:

| Comparison | Better | Worse | p |
| --- | ---: | ---: | ---: |
| `static` vs `postfilt` | 0 | 0 | 1.0000 |
| `static` vs `asof` | 13 | 0 | 0.0002 |
| `asof` vs `asof_item` | 10 | 0 | 0.0020 |
| `static` vs `asof_item` | 23 | 0 | < 0.0001 |
| `static_item` vs `asof_item` | 94 | 0 | < 0.0001 |

Per series, no arm with the knowledge-time projection is ever behind:

| Series (n) | static | postfilt | asof | static_item | asof_item |
| --- | ---: | ---: | ---: | ---: | ---: |
| HDPE film, China (13) | 12 | 12 | 12 | 2 | **13** |
| LDPE film, Vietnam all origins (11) | 8 | 8 | 11 | 1 | **11** |
| HDPE injection MFI>10, China (10) | 6 | 6 | 8 | 0 | **10** |
| HDPE blow moulding, Vietnam (9) | 5 | 5 | 6 | 1 | **9** |
| HDPE injection, China (9) | 7 | 7 | 9 | 0 | **9** |
| LDPE film, SE Asia dutiable (9) | 9 | 9 | 9 | 0 | **9** |
| LLDPE film, China (9) | 8 | 8 | 9 | 1 | **9** |
| LLDPE film, SE Asia dutiable (9) | 4 | 4 | 5 | 1 | **9** |
| HDPE injection MFI≤10 (7) | 7 | 7 | 7 | 0 | **7** |
| HDPE blow moulding, China (5) | 4 | 4 | 5 | 0 | **5** |
| LDPE film, SE Asia all origins (5) | 3 | 3 | 5 | 0 | **5** |
| LDPE film, China (4) | 4 | 4 | 4 | 0 | **4** |

## What the mechanism turns out to be

**Filtering after retrieval does nothing.** `static` and `postfilt` score identically, 77.0% each,
even though `postfilt` never lets a future issue into the context. Removing the future after
retrieval changed no answers on a single question — 0 better, 0 worse. The entire 13-point gain of
`asof` comes from spending the candidate budget only on issues that existed at the asked date, so
the right week is retrieved in the first place.

So on real data the advantage is not "hiding the future from the model". It is **allocating
retrieval to the eligible corpus**. A conventional index spends its top-k on whichever week is most
similar in wording, and on a weekly series where every issue looks alike, that is usually the wrong
week — filtering afterwards cannot recover a week that was never retrieved. This is the same
filter-order result the synthetic fixture produced, arriving here through a different failure mode
and on a corpus nobody in this team wrote.

**The two operations only work composed.** The item view alone is not merely useless, it is
destructive: `static_item` scores 6.0% and abstains on 92% of questions, because collapsing to "the
latest version" without a knowledge-time projection collapses to December for every question, and
the answerer correctly refuses to answer a March question from a December row. Give the same
collapse an eligible set to work in and it closes every remaining gap: 90.0% to 100.0%, ten
questions gained and none lost. Neither the clock nor the item view is the mechanism on its own. The
composition is.

**What the ten recovered questions were.** All ten failures of `asof` were read before the item arms
were written. Eight were recency starvation — the gold issue never entered the context at all,
because cosine similarity has no recency preference and on a weekly series every issue is worded
almost identically. Two had the gold issue in context and the answerer still quoted the neighbouring
week. The item view removes both: after collapse, the eligible latest row for the asked series is in
context on 100 of 100 questions, against 92 for `asof` and 79 for `static`.

## Disclosure: the item arms are post-hoc

`static_item` and `asof_item` were added after the three preregistered arms had been scored and
their failures examined. The collapse rule itself is generic — one current version per item as of
the asked date, the same operation the delivery fixture calls an item view — and it is not tuned to
any question, series or date. But it was chosen with knowledge of where `asof` lost, and it was
scored on the same 100 questions, so it is **not** an out-of-sample result. A clean confirmation
needs a fresh sample from the 598 candidate questions with the rule fixed in advance; that is the
next step and it is cheap.

A second caveat is sharper. These questions all take the form *"as of D, what is the most recent
assessment for series S"*, and the item view collapses exactly along that axis — latest version per
series. On this question form the projection is close to an oracle, which is why it reaches 100%.
That number should be read as "retrieval was the whole bottleneck on this question type", not as a
general accuracy claim. Question forms that aggregate differently — a range over time, a comparison
between two dates, anything needing superseded versions — are not tested here and would need the
item view relaxed. The honest general statement is the filter-order one: projection before ranking
dominates filtering after ranking, and the two compose.

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

## Cost

The two item arms cost 53,170 prompt tokens and 21,627 completion tokens for 200 answers, 211
seconds wall clock. Mean context per answered question: 958 tokens for `static`, 609 for `postfilt`,
959 for `asof`, 1,403 for `asof_item`. The projection buys its accuracy with a 46% larger context
than `asof`, because a collapsed pool admits more distinct series into the top-k.

## Limits

One product family, one year, one answerer, one repeat, 100 questions, one question form. The corpus
has no corrections, so the delivery clock is not exercised at all. The item arms are post-hoc on this
sample. Licensed content cannot be redistributed, so an external reader cannot rerun this without
their own subscription. The next steps are a fresh out-of-sample question draw with all five arms
fixed in advance, and putting LightRAG, Graphiti and Microsoft GraphRAG on this same index and
question set.
