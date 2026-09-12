# Recipient experiment verification

The initial tests failed against a receipt-blind Store: it returned the replacement before receipt, exposed an unreceived passage, and ignored receipt-log and microsecond boundaries. After the experimental adapter was implemented, the historical run recorded eight passing tests. The equivalent renamed commands are:

```text
.bench-venv/bin/python -m pytest benchmarks/test_delivery_projection.py benchmarks/test_delivery_review.py -q
8 passed (historical count; migration tests were rerun separately)

.bench-venv/bin/python -m benchmarks.verify_delivery_experiment
status: passed
```

Another agent within this project checked source cutoffs, recipient/source separation, hidden passages after warming semantic and lexical caches, graph visibility, and 40 concurrent alternating recipient requests. A second implementation in this repository recalculated every aggregate metric across all 250 method/query outcomes and verified full SQL/recipient payload equality, fixture uniqueness and source hashes.

Browser checks exercised the red/blue correction presets, the evidence-only failure, and SQL versus recipient comparison. All four report artifact links returned HTTP 200. Desktop 1440×1050 and mobile 390×844 screenshots were visually inspected; the mobile document width remained 390px and selects remained within their container. The final report retains all 50 recorded cases, five methods and the three explicit clocks.

Historical screenshots remain in the [baseline archive](CHANGELOG.md); they predate the naming migration. Machine-readable audit: `verification.json`. No production source or user profile changes were made.


The terminology and schema were migrated without rerunning inference. [Migration manifest](migration-manifest.json) records original and migrated hashes; [changelog](CHANGELOG.md) lists preserved historical exceptions. Numerical results and ranked text are unchanged. [User-provided external review](../EXTERNAL-REVIEW.md) reports a separate recomputation; its authorship and execution have not been independently authenticated.
