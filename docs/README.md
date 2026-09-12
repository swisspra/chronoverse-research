# Chronoverse evidence and documentation

The application is described in the root README. Historical retrieval results are in `benchmarks/` and `benchmarks-v2/`; the active recipient-delivery report is in `benchmarks-delivery/`. The next-round protocol and status are in `benchmarks-next/`.

## Artifact storage and provenance policy

Raw result JSON and original source snapshots are retained in Git so audits and static reports work without an additional object server. The two largest historical JSON files are about 19 MB each, below GitHub's per-file limit; Git's lossless object compression keeps this initial evidence package manageable. We choose direct Git storage for this round, without Git LFS or lossy rewriting. Downloaded corpora, vectors, model weights, runtime databases, user profile data and credentials are ignored. If future artifacts exceed practical Git limits, a separately reviewed migration will use compressed archives plus hashes and documented extraction.

The tag `round-3-as-published` preserves the first imported project state and all application constants. This establishes history from the import onward; it does not prove the original runs were preregistered. Old source hashes and raw results remain historical evidence. New runs record commit, tree state, runtime, package freeze and source hashes. New hypothesis-driven results additionally record the committed predictions file and specification.

The sibling research repository remains local and has a separate history; it is not published as part of the application's repository.

## What verification means

Artifact checks described as “independent,” “independently recomputed,” or a “second implementation” were written or run by additional implementations or agents within this same project team. They help detect implementation and packaging errors; they are not unaffiliated external replication, peer review, or independent authorship of the underlying datasets. The separately supplied external review has its own attribution and authentication limits in [EXTERNAL-REVIEW.md](EXTERNAL-REVIEW.md). Each verifier documents which quantities it reconstructs and which it merely checks for integrity.

## Larger next-round artifacts

New artifacts larger than GitHub's single-file limit are published as deterministic `*.json.gz` files plus a small summary containing compressed and uncompressed SHA-256 hashes. Decompression restores original result bytes exactly. The historical direct-JSON policy remains unchanged; `gzip -dc FILE.json.gz > FILE.json` reconstructs a new compressed result for its verifier. The scaled fixture is compressed using the same lossless policy.

The full500 answer manifest uses ordered deterministic gzip chunks because its complete compressed stream is also large. Its manifest records each part's byte count and hash plus the combined uncompressed hash. Concatenating the decompressed parts in the manifest's order reconstructs the exact original JSONL; the streaming verifier checks this without requiring the full file in memory.
