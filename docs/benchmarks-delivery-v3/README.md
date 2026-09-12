# Delivery v3: filter order helps; answer sufficiency remains unsolved

Receipt filtering **before lifecycle projection** recovers support that filtering
after projection has already removed. Ordinary SQL and Delivery projection return
identical top-five contexts, scores and candidate projection hashes on all **658
queries**. This establishes conventional SQL implementability, not a new ranking
advantage over SQL. The separately labeled item view can also return received
passages and notices without requiring an active parent assertion.

All six methods repeated the full query set twice with identical text, score,
evidence, event-state, graph and candidate signatures. Measurement code was frozen
at `ed95e8f3ebaf139047c54ced7c0f532efc66030d`. The fixture contains **7,314
assertions, 611 events and 152,048 receipts**, with **108 DEV, 500 TEST and 50
compatibility questions**. No production ranking defaults changed and no paid API
calls were made in this retrieval experiment.

## Held-out TEST results

| Method | Complete support | Support recall | Context-unit precision | Queries with unreceived items | Empty abstention |
|---|---:|---:|---:|---:|---:|
| Global temporal | 31.29% | 44.38% | 9.32% | 59.20% | 0% |
| Scalar clock | 34.12% | 46.67% | 9.80% | 52.80% | 0% |
| Filter after projection | 31.29% | 44.38% | 9.32% | 0% | 0% |
| Ordinary SQL receipt filter | 80.94% | 84.57% | 17.76% | 0% | 0% |
| Delivery projection | 80.94% | 84.57% | 17.76% | 0% | 0% |
| Delivery explicit item view | 98.59% | 98.86% | 20.76% | 0% | 0% |

The denominator matters. TEST has **425 answerable questions**, **75 questions
without gold support**, and **525 gold support units**. Complete support is the
fraction of the 425 answerable questions with every required unit. Support recall
is recovered units divided by 525. Context-unit precision divides recovered
support units by the **2,500 returned top-five contexts**; it is not claim truth
probability or generated-answer accuracy. A supported assertion requires its
specified passages. Orphan passages and explicit notice questions remain
answerable units even when no active assertion can be returned.

All methods return five contexts for every TEST question, including all 75
without relevant support. Consequently **exact support-set rate and empty
abstention are both zero for every method**. Availability filtering reduces
unreceived context; it does not decide whether the remaining context answers the
question. The item-view result is a capability extension with additional result
types, so its improvement must not be presented as a like-for-like ranking gain.

## Correction families and uncertainty

The predeclared primary group contains **175 TEST assertion questions** from
`delayed_correction`, `delayed_retraction`, and `historical_event_receipt`.
Event-only questions are excluded from this group. Delivery recovers complete
support for **174/175**; Global, Scalar and filter-after-projection each recover
**0/175** in this deliberately constructed group.

For each of those three pooled comparisons, the complete-support difference is
**+99.43 percentage points**, with a **Bonferroni simultaneous 95% bootstrap
interval of +97.14 to +100.00 points**. Holm-adjusted paired permutation
`p = 0.0011998800119988001`. The correction family contains 12 comparisons: pooled
and individual-family contrasts against the three baselines. Per-family values,
scenario-entity resampling, and a scenario-template cluster sensitivity analysis
are retained in [analysis.json](analysis.json). These synthetic entities do not
become independent real-world observations because an interval is computed.

The item extension retrieves the gold notice in **50/50 TEST notice questions**
and the standalone passage in **25/25 evidence-only questions**; the
assertion-only Delivery arm recovers none in these two groups. They form a
separate exploratory capability comparison family. Their degenerate bootstrap
intervals reflect all-success versus all-failure synthetic cases, not certainty
on unseen documents.

## Frozen DEV gate: precision gain does not solve abstention

The gate was calibrated only on DEV and committed at
`f891666` before TEST evaluation. It filters the existing top five using their
rounded cosine component; it cannot recover a missing candidate. The objective,
grid and coverage constraint are preserved in
[frozen-dev-gate.json](frozen-dev-gate.json).

| Arm | Complete support before → after | Context-unit precision before → after | False abstention before → after | Empty abstention after |
|---|---:|---:|---:|---:|
| Delivery / ordinary SQL | 80.94% → 79.76% | 17.76% → 20.71% | 0% → 17.65% | 0% |
| Delivery item view | 98.59% → 97.41% | 20.76% → 20.66% | 0% → 0% | 0% |

The gate still returns context for **all 75 no-support TEST questions**. Its
precision increase for Delivery comes with lost support and abstention on
answerable questions; the item-view gate slightly worsens precision and support.
This is **not evidence to promote the gate to production**. Full before/after
results for every method and family are in
[sufficiency-test.json](sufficiency-test.json). No threshold was changed after
these TEST results were observed.

## Artifacts and verification

- [summary.json](summary.json): compact metrics, split/family diagnostics, model,
  timing, original measurement provenance and compression hashes.
- [results.json.gz](results.json.gz): byte-exact compressed original result,
  including all 3,948 method/query records. Uncompressed SHA-256:
  `c42122de159264f1eb6dbc34ec7d02552615ac1a9510a6e46b2bfb2d4ecb00e3`.
- [retrieval-contexts.json.gz](retrieval-contexts.json.gz): exact original answer
  experiment context inputs. This artifact itself does not claim answers were
  generated. Uncompressed SHA-256:
  `d8f12a099d7e159d777959df8abd28611df2bef9b7382361e97b131e25fddf2e`.
- [PROTOCOL.md](PROTOCOL.md): item scope, measurement and support conventions.

Compression uses gzip `mtime=0`; original JSON files remain in the isolated run
workspace. Measurement, later statistical analysis, gate calibration/evaluation,
and packaging have separate provenance. Later writes correctly retain
`git_dirty=true` when only that writer's previously generated artifacts caused
the recorded exact-path exemption; they are not relabeled as clean trees.

```sh
.bench-venv/bin/python -m benchmarks.verify_delivery_v3 \
  --input-dir docs/benchmarks-delivery-v3 \
  --fixture benchmarks/data/delivery-v3.json.gz
```

This read-only verifier is a second accounting implementation. It reconstructs
support and unreceived-item leakage directly from fixture gold, original text,
source timestamps and individual receipts, and checks summaries and D/E context
identity. A negative test changes support while updating the container hashes;
verification still fails. The same CLI also verifies the committed frozen gate
bytes and source-result hashes, then recomputes all 3,000 TEST method/query gate
results from the saved rounded cosine scores without importing the gate evaluator.
A separate corrupted-metric test fails as expected. It does **not** independently rerun embedding ranking
or reconstruct lifecycle candidate projections. Those boundaries are explicit.

Total runtime was **967.61 seconds**. All arms share one isolated immutable ledger
and exact-text vector storage. First-repeat timings include incremental vector
preparation; later repetitions encode every query fresh. Instrumentation and
concurrent local experiments affect timings, so these are diagnostic measurements.
The 50 historical questions/data remain intact, but added distractors change
ranking competition: no numerical equality with the old isolated 50-query run is
claimed. Scenario-template language and shared parent mechanisms limit external
generalization; uploaded real documents still need representative evaluation.
