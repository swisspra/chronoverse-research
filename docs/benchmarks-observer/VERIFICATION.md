# Observer experiment verification

The initial tests failed against a receipt-blind Store: it returned the replacement before receipt, exposed an unreceived passage, and ignored receipt-log and microsecond boundaries. After the experimental adapter was implemented:

```text
.bench-venv/bin/python -m pytest benchmarks/test_observer_projection.py benchmarks/test_observer_review.py -q
8 passed in 0.14s

.bench-venv/bin/python -m benchmarks.verify_observer_experiment
status: passed
```

The independent reviewer checked source cutoffs, observer/source separation, hidden passages after warming semantic and lexical caches, graph visibility, and 40 concurrent alternating observer requests. The independent artifact auditor recalculated every aggregate metric across all 250 method/query outcomes and verified full SQL/observer payload equality, fixture uniqueness and source hashes.

Browser checks exercised the red/blue correction presets, the evidence-only failure, and SQL versus observer comparison. All four report artifact links returned HTTP 200. Desktop 1440×1050 and mobile 390×844 screenshots were visually inspected; the mobile document width remained 390px and selects remained within their container. The final report retains all 50 recorded cases, five methods and the three explicit clocks.

Screenshots: `report-desktop.png`, `report-mobile.png`. Machine-readable audit: `verification.json`. No production source or user profile changes were made.
