# Provenance of this public repository

This repository is a **published snapshot**, not the development history.

## Where the history lives

Chronoverse was developed in a private repository. Every result file under `docs/` embeds a `provenance` block recording the exact commit of that private repository, the dirty flag, the Python and platform versions, the frozen requirements hash and, for the preregistered rounds, the `PREDICTIONS.md` commit and hash. Those commit identifiers refer to the private history and will not resolve here.

This snapshot corresponds to private commit `be03399071cf3b3a520747af925f40a597f96045`.

## What that means for verification

Verification of the published numbers does **not** depend on the commit graph. Every verifier in `benchmarks/verify_*.py` re-derives metrics from the published artifacts and their SHA-256 content hashes:

```bash
make verify
```

That checks backend and benchmark test suites, recomputes cross-domain, delivery, FANToM, hosted-retrieval and answer-continuation results from the raw artifacts, and fails on any perturbation. It needs no network and no private history.

Two operations do need the private history and are therefore not reproducible from this snapshot alone:

- `benchmarks/aggregate_answer_continuation.py`, which pins a frozen statistics worktree at a specific commit before re-aggregating.
- Any `git rev-parse` of the commit identifiers recorded inside result files.

The published summaries and audits for those steps are included, so their outputs remain checkable against the raw records even though the re-aggregation command is not runnable here.

## What was left out of this snapshot, and why

Two directories of prepared **inputs** were excluded to keep the repository a reasonable size. Neither backs any published result: both are offline-prepared context sets for experiments that have not been run, or superseded versions of a context set that was replaced before any answer was generated.

| Path | Size | Reason |
| --- | ---: | --- |
| `docs/benchmarks-next/answer-full500/` | 116 MB | Prepared 500-question answer contexts, 18 gzip parts plus manifest. No paid inference was ever dispatched against them. |
| `docs/benchmarks-next/archive/` | 23 MB | Two superseded versions of the 50-question context set, retained privately for audit. The version actually used is `docs/benchmarks-next/answer-contexts-50.jsonl.gz`, which is present here. |

A full SHA-256 inventory of both directories is kept with the private repository; the manifest hash of the excluded full-500 set is `3e3e53eb808f7012a421020e4c6fd58d1f10fa0acf2453ae315a0251787b7d43`. Ask if you need them and they can be shared out of band.

Research notes, design documents and exports that belong to unrelated private work were also removed before publication. They contain no Chronoverse result and nothing referenced by any claim here.

## Independent review

An external review recomputed the headline figures of several rounds from the raw artifacts with independently written scoring code, including the BEIR cross-domain cells, the delivery-v3 leakage and support tables, the FANToM accuracies under the official list-matching rule, and the answer-track statistics. See `docs/EXTERNAL-REVIEW.md`.
