# Observer receipt experiment: results

[Open the interactive report](index.html). This is an isolated local experiment using the existing MiniLM model and unchanged Chronoverse ranking. The production application, MCP tools, user profiles, and earlier benchmark results were not modified.

## What the experiment establishes

Recording when each observer receives information prevents context from crossing the scenario's receipt/time boundary. Applying that filter before lifecycle projection also preserves an older report until its correction or retraction reaches the observer.

**An ordinary SQL implementation achieves the same result as the observer adapter:** all 50 full result payloads, scores, and candidate projections match. This supports adding receipt metadata where the product needs it. It does not justify a special quantum mechanism or establish a novel retrieval algorithm.

The scenario distinguishes three clocks:

- `valid_at`: which modeled world time the question concerns.
- `known_at`: which ledger and receipt records the system may use.
- `observer_at`: the latest receipt time allowed for that observer.

Receipt means explicitly recorded availability. It does not prove that a human read, understood, agreed with, or believed the content. Received lifecycle events follow a fixed scenario policy for active context; agent-specific trust or disagreement with that policy is not modeled. A correction event retires the old source claim under that policy without certifying its replacement as physical truth.

## Recorded comparison

The fixture has **50 unique questions, 18 assertions, 3 lifecycle events, and 48 receipt records**. There are 32 answerable questions and 18 empty-support questions, with 36 expected support units. The same top5 ranking, model, thresholds and weights are used throughout.

| Method | Queries with out-of-scope items | Support recall | Support precision | Correct empty abstention |
| --- | ---: | ---: | ---: | ---: |
| Global temporal Store | 48.0% (24/50) | 83.3% (30/36) | 31.3% | 11.1% (2/18) |
| Earlier scalar clock | 48.0% (24/50) | 83.3% (30/36) | 30.6% | 11.1% (2/18) |
| Receipts after global projection | 0% | 80.6% (29/36) | 43.9% | 55.6% (10/18) |
| Ordinary SQL receipts before projection | **0%** | **97.2% (35/36)** | **47.3%** | **55.6% (10/18)** |
| Observer adapter before projection | **0%** | **97.2% (35/36)** | **47.3%** | **55.6% (10/18)** |

These percentages describe this small synthetic diagnostic, not general factual accuracy or an expected production uplift. Leakage includes receipt-log and source-recording cutoffs, not only whether a person physically received a message. The global baseline returned 62 out-of-scope item appearances across questions; this is not a count of 62 distinct documents.

The post-projection filter removes visible leaked fields but cannot restore an old claim that an unseen correction has already suppressed. This is why filtering order matters even without a quantum or probabilistic model.

## Inspectable examples

- `oq10`: Red has the original Cobalt storm report, but has not received its correction. Global state discards the old report; receipt-aware projection retains it.
- `oq14`: Blue has both conflicting storm reports, but has not received the correction event. Both reports remain visible; receiving a second claim does not establish a winner.
- `oq11`: Red receives the correction before receiving the replacement claim. No active claim supports the answer at that moment. The fixture retains the correction as a diagnostic event annotation.
- `oq41`: Blue has a standalone evidence passage but no receipt for its parent assertion. The assertion-centric adapters miss that legitimate passage. It remains answerable gold and accounts for the observer method's missing support unit.

The red/blue examples show their actual coordinates; they are not described as observations at the same instant when their timestamps differ. The first fixture draft contained repeated query scopes; it was retained as `benchmarks/data/observer-v1-draft.json` and replaced during preflight, before any retrieval results were measured. The evaluated fixture contains 50/50 unique observer/query/scope combinations.

## Limitations that remain

**Zero receipt leakage is not sufficient answer quality.** The observer method still returns irrelevant received assertions: precision is 47.3%, and only 10 of 18 empty-target questions abstain. A sufficiency classifier was deliberately not added or tuned during this experiment.

A useful next implementation would make evidence independently retrievable, exposing only fields the observer received, and preserve received lifecycle notices even when active assertions are absent. It would also expose clear policy/observer coordinates through MCP. Production identity authorization, delivery integration, per-agent trust/acceptance policy, and large-scale performance require separate work.

Gold was manually authored independently of the adapter, but it is a small designed fixture with shared vocabulary. Fifty questions are not fifty independent real-world samples. There is no held-out generalization claim, generated answer model, LLM judge, quantum computation or consciousness claim. The strong SQL control demonstrates that ordinary classical filtering suffices for these semantics.

## Timing and cost

All model calls were local; paid API calls: **0**. Recorded preparation took 1.02 seconds and the runner took 2.43 seconds overall on this small dataset. Warm per-query p50 was 5.33ms globally, 5.89ms for SQL receipts, and 5.60ms for the observer adapter. Document vectors were warmed and query encoding was freshly computed for each timed request. Different eligible corpus sizes and shared-machine conditions make these diagnostics, not controlled capacity comparisons or comparisons with the larger SciFact run.

## Verification and reproduction

Eight observer tests passed, covering delayed lifecycle receipt, exact receipt/recording boundaries, source-record cutoffs, source/observer separation, unseen evidence in warmed semantic/lexical caches, graph visibility and concurrent observer isolation.

An independent audit reconstructed receipt/source visibility directly from the fixture and recomputed every method's support/leakage measures. It verified full SQL/observer result equality, the evidence-only failure, fixture uniqueness, and archived source hashes. Production source hashes still match the previous benchmark round.

```bash
.bench-venv/bin/python -m pytest benchmarks/test_observer_projection.py benchmarks/test_observer_review.py -q
.bench-venv/bin/python -m benchmarks.observer_experiment
.bench-venv/bin/python -m benchmarks.verify_observer_experiment
.bench-venv/bin/python -m benchmarks.render_observer_report
python3 -m http.server 8003 --bind 127.0.0.1 --directory docs
```

The runner enforces the frozen fixture hash and checks source stability during measurement. It writes isolated temporary ledgers and leaves user profiles untouched. [Protocol](PROTOCOL.md), [full results](results.json), [fixture](fixture.json), [independent audit](verification.json), [executed source](source/), [previous experiments](../benchmarks-v2/index.html).
