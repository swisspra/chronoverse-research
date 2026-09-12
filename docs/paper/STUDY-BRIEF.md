# Chronoverse and Graphiti: comparative study brief

Status: planned next study. Finish and audit the current pilot and local benchmark queue before starting this study. This brief is not a preregistration, completed paper, novelty claim, or authorization to submit publicly.

The main comparison is **Chronoverse versus native Graphiti on FANToM and LongMemEval**. FANToM is an evaluation dataset, not a competing memory system. Published Zep results cannot substitute for running the pinned open-source Graphiti implementation. Current static retrieval gains and synthetic delivery results remain separately attributed preliminary evidence.

## Questions and controls

Test whether recipient-specific lifecycle handling improves answers about evolving claims and uneven information access, under explicitly defined valid, recorded and delivered times. Determine which gains survive strong raw RAG, long-context, reranked RAG and conventional SQL controls. The existing exact SQL tie must remain visible: it rules out attributing the synthetic ordering result uniquely to graphs.

Separate two tracks. A semantic-control track gives both systems the same explicitly annotated events and metadata. An end-to-end track starts both systems from the same raw documents or messages, counting extraction failures, annotation requirements, ingest calls and costs. Chronoverse must not receive free gold facts or lifecycle labels while Graphiti must infer them. Common adapters must be gold-free and their output available equally to both systems.

Include a strong native Graphiti configuration using its supported group boundaries when recipient isolation calls for them. Do not force an unnecessarily global graph as the sole competitor. Measure any per-recipient duplication, incremental ingest and storage costs explicitly, and choose configurations on DEV rather than after TEST scores.

On each public dataset, first establish what its timestamps and labels actually mean. Session dates are not automatically source-recording or receipt times. Retain the current LongMemEval strict-cutoff loss and its metadata diagnosis; do not relabel that custom filter as Chronoverse or alter public gold to favor it. Public datasets without recipient receipts cannot establish a three-clock advantage. Any new receipt/lifecycle annotations or synthetic extension need separate naming, provenance and independent annotation checks.

## Frozen experimental design

Before scored calls, freeze dataset revisions, splits, adapters, system commits, extraction prompts, answer prompts, graph construction, embeddings, reranking, context budgets, model identities, grader rubric, seeds, repetitions and primary contrast families. Keep DEV tuning separate from TEST. The existing pilot's 50 questions belong to the 500-question synthetic set; they are not fresh independent test cases.

Run both a controlled shared-model/shared-budget comparison and, if affordable, a separately labelled comparison of each system's best declared configuration. Track effective text coverage as well as nominal token limits. A model, provider, context-length or extraction change is a named experimental change. A provider switch starts a separately attributed run and never silently changes one arm midway.

Include clock ablations, lifecycle projection order, raw versus reranked retrieval, and sufficiency/abstention controls where the task supports them. Do not expand the family of confirmatory claims after results are visible. Cold ingest, cold query, warm query and cache reuse need separate measurements with exact keys and invalidation rules. Shared-machine timing is observational unless resource isolation is controlled.

## Outcomes and audit

Use official public task definitions and graders where available, pinned to their source versions. FANToM information-access diagnostics must not be presented as official belief/answer leaderboard performance. LongMemEval session recall is a retrieval diagnostic and must not be called answer accuracy or passage-support accuracy.

Measure answer correctness, eligible supporting evidence, correction recovery, stale and unreceived citations, unsupported answers, abstention, latency, tokens and cost. Literal answer matching alone is insufficient for a publication claim: include blinded semantic adjudication, audit false-positive matches such as negation, and preserve disagreement records. Graders should not know system names or experimental arm identities. Report grader-model identity and sensitivity to its errors.

Retain timeouts, malformed responses, model mismatches, truncated completions and uncertain charges. Show their rates per arm and distinguish instrument limits from semantic failures. Missing attempts cannot silently disappear from planned correctness denominators, and an invalid answer cannot be presumed leak-free. Any completion-cap repair preserves the original run and receives its own protocol amendment.

Use the query or relevant independent conversation as the paired unit; repeated calls are not new examples. Report effect sizes, raw and simultaneous confidence intervals, multiplicity-adjusted p-values, per-family outcomes and failure examples. Determine sample size from desired precision or power after an explicitly exploratory pilot; do not promise precision merely from a round number of cases. Account for shared templates and conversations.

## Budget and publication gates

Measure native ingest cost on a bounded public-data pilot before scaling. The successful two-episode Graphiti connectivity smoke is not a reliable price estimate for complete LongMemEval graphs. Freeze a concrete request/token/money envelope from measured data before a large API run; private-proxy prices remain unknown. Preserve endpoint/model-specific caches and uncertainty accounting.

The deliverable is an English paper draft with primary-source citations, formal task definitions, system descriptions, complete methods, positive and negative results, limitations, ethics/data-license notes, appendices and a reproducibility package. Figures and tables must be generated from retained artifacts. Novelty claims require a substantive prior-work review, including temporal databases, distributed knowledge/access and evolving-graph memory.

An arXiv-ready source/PDF package is a target, not a claim that the work is accepted, novel or ready to submit. Public submission remains a separate action after the results, citations, authorship, licenses and final text are reviewed. The conclusions follow the evidence even if strong baselines tie or outperform Chronoverse.
