# Separate sufficiency experiment, frozen before DEV calibration

Use the v2 gate grid unchanged: absolute cosine 0.20–0.80 in steps of 0.10, relative margins 0.02/0.05/0.10/0.20/1.00. Retain a recorded top-five candidate only when its cosine passes the absolute threshold and lies within the margin of the best cosine in that pool. Preserve ranking order. Production score components are rounded to four decimal places; that recorded precision is the input to this experiment.

Choose each method's gate on the 108 DEV questions only: maximize micro F0.5 while retaining any context on at least 60% of answerable DEV questions; ties prefer recall, precision, lower absolute threshold, larger margin. If no candidate is feasible, report the failed coverage constraint and retain the best objective only as a diagnostic. The TEST records cannot be accessed by the selection function; a poisoning test enforces this boundary.

Write and commit the DEV choice before invoking TEST evaluation. Record its file hash, commit and exact source retrieval-result hash. Report before/after support precision, recall, answerable coverage, empty-support abstention, false abstention, and leakage per family and pooled. Filtering cannot erase a leaked item unless it removes that item, and cannot restore support absent from the top-five pool.

This fixture shares parent mechanisms across distinct entities/scenario variants in DEV and TEST. It is not representative uploaded-document validation, and the resulting gate is not promoted into the product. Cosine is not a calibrated confidence in truth.
