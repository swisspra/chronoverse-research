# Benchmark verification — 2026-09-12

- `.bench-venv/bin/python -m pytest benchmarks/tests benchmarks/test_temporal_fixture.py -q`: **266 passed**. These validate metrics and generated scenario expectations, not product superiority.
- Real browser: all three report tabs, nDCG/Hit@1 switching, A-loses filter, empty-gold filter and query/category search worked. Retraction search matched 12 cases; all empty-gold cases matched 36.
- All six local source/download targets and the linked SciFact protocol returned HTTP 200.
- Desktop screenshot inspected at 1440 × 1050; mobile at 390 × 844. Mobile document width equaled viewport width (390 px).
- Production `store.py`, `semantic.py` and `models.py` SHA-256 values still match the measured source manifest.
- App profile counts remained demo: 17 assertions / 3 events; Document Sandbox: 3 assertions / 0 events. Benchmark datasets used isolated ledgers.

Screenshots: [desktop](report-desktop.png), [mobile](report-mobile.png).
