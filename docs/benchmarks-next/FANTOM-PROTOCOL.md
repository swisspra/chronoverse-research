# FANToM presence-rule adapter diagnostic — protocol v1

This protocol fixes the mapping before TEST labels are scored. Metadata inventory and parser coverage may be inspected before freezing. No performance score may be calculated until this document and the adapter have been committed. This is a public-data **presence-rule diagnostic**, not a passage retrieval benchmark, generated-answer evaluation, theory-of-mind claim or official FANToM leaderboard submission.

## Source and inventory

Use official FANToM v1 from the [pinned upstream repository](https://github.com/skywalker023/fantom/tree/1cae6fa30f5ba04ca0fff5f5716b5ba7055e2e85), commit `1cae6fa30f5ba04ca0fff5f5716b5ba7055e2e85`. The [official loader](https://github.com/skywalker023/fantom/blob/1cae6fa30f5ba04ca0fff5f5716b5ba7055e2e85/task/dataset_loader.py) specifies archive SHA-256 `1d08dfa0ea474c7f83b9bc7e3a7b466eab25194043489dd618b4c5223e1253a4`. Record archive, extracted JSON, adapter, protocol and official evaluator hashes in the result. The repository's [MIT license](https://github.com/skywalker023/fantom/blob/1cae6fa30f5ba04ca0fff5f5716b5ba7055e2e85/LICENSE) is recorded; no additional dataset-specific terms were found in the supplied loader. This is not a claim about unexamined downstream rights.

The dataset contains 870 question sets, 253 conversation IDs and 368 part IDs. Its original question fields contain 870 FactQ, 1,540 BeliefQ, 870 information-access list, 870 answerability list, 3,571 information-access binary and 3,571 answerability binary questions. These inventory counts must match exactly. The official evaluator also derives a multiple-choice copy of each BeliefQ; the 1,540 additional copies are not separate supplied dataset records and remain unrun here.

Each binary family contains 557 `no:long` records, so the official short-input convention leaves 3,014 eligible binary questions per family; full input retains all 3,571. List questions retain all 870 per family in both modes. These are label-inventory counts only, inspected without evaluating adapter predictions.

## Gold-free ingress

`public_input` copies only `set_id`, `part_id`, `conv_id`, `full_context`, `short_context` and `joining_speaker`. No `correct_answer`, `wrong_answer`, `missed_info`, `missed_info_accessibility`, belief annotation or fact answer is admitted. A strong test poisons every such annotation and proves identical contexts and receipts. Predictions are prepared for every set, input mode and method **before** evaluation questions or labels are extracted.

Each set receives a separate scoped view, identified by its original set/part/conversation IDs; views are not combined across sets. Multiple sets can describe the same conversation with different selected windows. Turn positions are ordinal coordinates, not invented wall-clock timestamps. No asserted facts or lifecycle events are extracted from prose.

## Frozen presence rule

1. Parse nonempty lines using `speaker: text`; any unparsed line marks the set unmappable. Do not silently join or discard such lines.
2. Require the entire parsed short context to occur exactly once as a contiguous sequence of `(speaker, text)` pairs in the full context. Zero or multiple alignments are unmappable.
3. Read the provided `joining_speaker`. If its first short-context turn is after position zero, infer absence over `[0, first-own-turn)` and arrival at that first own turn.
4. If its first turn is position zero, interpret that turn as an initial departure and its next own turn as return. Infer absence over `(0, next-own-turn)`. Missing return or an empty inferred absence window is unmappable. This structural rule is fixed; no phrase classifier or gold label chooses the boundary.
5. Speakers occurring anywhere in the selected short context, except the joining speaker during the inferred gap, receive every short-window turn at that turn's ordinal position. Full-context speakers absent from the short window receive no short-window turns. This is a coarse attendance assumption, not proof of hearing, understanding or remembering.
6. The diagnostic target is **all turns in the inferred absence window**, not a fact-answer-selected passage. A recipient is predicted to have access only if every target turn is available under the method. The same predicted recipient list is used for information-access and answerability questions. This deliberate limitation can produce identical predictions where the external labels differ.
7. Metadata-only preflight found 241 initial-departure cases, 629 first-turn-arrival cases and one short/full alignment failure: 869/870 sets mapped. The failed set is retained, with no prediction; no rule is changed to repair it after scoring.

This rule ignores semantic target localization, later paraphrases, implicit arrivals/departures, statements about other characters and information repeated outside the selected window. It can be wrong even when parsing succeeds. The selected absence window is a **derived diagnostic target**, never represented as official passage relevance judgments.

## Five fixed methods

| Method | Available target-window turns |
| --- | --- |
| Global temporal | All context turns for every speaker appearing in the selected short/full input |
| Scalar clock | Same common end-of-context cutoff for all recipients; no recipient receipt information |
| Filter after projection | Start with the global turn sequence, then filter by inferred receipt membership |
| Ordinary SQL receipt filter | Separate SQLite `SELECT DISTINCT` over receipt rows for recipient and cutoff |
| Delivery projection | Filter inferred receipt rows before constructing available turn positions |

There are no lifecycle transitions, vector rankings, generated claims, model calls or calibrated gates in this diagnostic. Global and scalar are expected to tie; the three receipt-aware methods are expected to tie because filtering order has no destructive lifecycle projection here. This experiment tests whether the **heuristic public-context mapping** agrees with external labels. It does not measure Chronoverse Store retrieval quality or provide evidence for correction-recovery superiority. No manufactured lifecycle events will be added to create separation.

## Evaluation-only labels and metrics

Follow [the pinned official evaluator](https://github.com/skywalker023/fantom/blob/1cae6fa30f5ba04ca0fff5f5716b5ba7055e2e85/eval_fantom.py) for these limited scoring conventions:

- In `short` mode, exclude binary records labelled `no:long` from eligible scoring, after predictions are fixed. Keep every excluded record and its reason in raw output. In `full` mode retain them and normalize `no:long` to `no`.
- Binary: report accuracy plus support-weighted class F1 for yes/no. Invalid/unmapped predictions count as wrong in the all-eligible denominator; also report mapped-only accuracy and mapping coverage.
- List: use the official criterion that every correct name must occur and no wrong name may occur in the predicted-name response, case-insensitively. This mirrors official substring matching, which is weaker than arbitrary exact set matching. No list answer is used to create the candidate roster.
- Report every family separately for short/full inputs, with raw, eligible, excluded and mapped counts. These pooled family measures combine original accessibility/control annotations; they are **not** the official scenario-split `All`, `All*` or consistency leaderboard metrics.
- FactQ and BeliefQ remain fully inventoried but unscored: they require semantic answers/belief reasoning and provide no passage qrels. Their omission is explicit, not a zero score or a deleted question type.

The official information-access prompt includes the supplied fact answer. This adapter **does not** ingest that answer, because gold-free receipt construction is the purpose of this track. Answerability uses a fact question in the official prompt, but this rule does no semantic matching of that question either. These input and capability differences forbid a direct leaderboard comparison.

## Artifacts and execution

`python -m benchmarks.fantom_adapter` prints only inventory/coverage. After the parent commits this protocol and adapter, `--score` runs the fixed diagnostic. It uses `BenchmarkRun`, refuses an uncommitted run unless `--allow-dirty` is explicit, records source/runtime/PREDICTIONS provenance, and saves all query labels, predictions, exclusions, parsed contexts, derived receipts and per-method receipt traces. No paid call or model inference occurs.

Raw outputs reference original set IDs and ordinal turn IDs. Mapping-only timing is not model or product latency. Related sets share conversations, so no independent-question statistical significance is claimed. Report all mismatches and ties without adjusting this rule. A true generated-answer track remains pending an authorized answerer and faithful official prompt/evaluation implementation.
