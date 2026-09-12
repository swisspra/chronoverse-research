# Recipient receipt experiment v1: fixed protocol

## Question

Does recording when a particular recipient received an assertion, evidence passage, or lifecycle event prevent context leakage and premature suppression of that recipient's earlier knowledge? Does a special recipient projection outperform an ordinary receipt/time SQL filter using the same information?

This is an experiment in recipient-specific database views. Receipt means availability in the scenario, not agreement, truth, or proven human comprehension. Recipient identity is separate from source perspective.

## Frozen comparison

Use the existing local MiniLM model and unchanged Store lexical/vector/one-hop ranking, weights and thresholds. No API calls or generated answers. Fixed top5 context retrieval; no tuning on evaluation labels. Fixture gold is authored by a separate agent within this project without querying the implementation, then frozen before scoring. Synthetic authoring remains a limitation.

Five methods:

1. Global temporal Store: knows what the shared ledger knows.
2. Scalar clock: uses the earlier of recipient time and ledger cutoff, without individual receipts.
3. Post-projection receipt filter: filters assertions/passages/events after global lifecycle projection, before ranking. This avoids artificial top-k candidate starvation but cannot restore claims already retired by unseen events.
4. Ordinary SQL receipt/time filter: separately reconstructs eligible claims, evidence and lifecycle state using receipt joins before ranking.
5. Recipient projection: applies recipient receipt visibility before the existing Store lifecycle projection and ranking.

A received item is visible only if its source record is known by `known_at`, a matching receipt is recorded by `known_at`, and `received_at <= received_by`. Assertion, passage and event delivery are separate. Late receipt logging must not leak into an earlier ledger snapshot. Valid-time intervals remain half-open. Correction/retraction effects require receipt of the event; an event may retire a received assertion before its replacement arrives. All methods use the same raw ledger and fixed question coordinates. No user profiles are modified.

## Measures

Report top5 relevant support precision/recall, exact support-set rate, empty-gold abstention and false abstention. An expected passage must actually accompany the returned assertion to count as supported retrieval. Audit assertion, passage and lifecycle-event visibility separately; invisible events that suppress an answer are captured by missing-support cases even when no event is returned. The SQL reference establishes visibility, not relevance gold.

Also report all-candidate projection equivalence and top5 ID/score equality between ordinary SQL filtering and the recipient adapter. A tie means ordinary filtering implements the needed semantics; it is not evidence of novel retrieval advantage.

Run every method once to warm the derived document index, then measure fresh query encoding per request. Separate preparation and warm request timing. Shared-machine timings and differing eligible context sizes preclude a controlled throughput claim. Preserve fixture, code and model hashes, all predictions, scope coordinates and failure examples in a standalone local report.


The terminology and schema were migrated without rerunning inference. [Migration manifest](migration-manifest.json) records original and migrated hashes; [changelog](CHANGELOG.md) lists preserved historical exceptions. Numerical results and ranked text are unchanged. [User-provided external review](../EXTERNAL-REVIEW.md) reports a separate recomputation; its authorship and execution have not been independently authenticated.
