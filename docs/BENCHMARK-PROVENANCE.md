# Benchmark provenance and verification

New benchmark result writers capture the Git commit, dirty paths, description,
Python/platform/load, source SHA-256 hashes, and the literal installed package
`Name==Version` snapshot with its SHA-256. If `PREDICTIONS.md` exists, its hash and
last commit are recorded; a commit is claimed only when those committed bytes
match the current file exactly. Historical result files remain pre-Git snapshots.
Their archived sources and original hashes are retained without invented commits.

Run result-producing commands from a clean committed tree. `--allow-dirty`
explicitly permits an uncommitted run and records that choice. Source, commit,
package, requirements, and prediction changes during a run still reject writing;
restart the run after such a change. The writer rechecks before each atomic JSON
write. Subsequent writes exempt only exact output paths previously written by
that same writer, after checking their bytes; all dirty paths remain visible in
provenance. It never exempts an entire output directory.

`BenchmarkRun.write_json(path, payload)` attaches provenance.
`BenchmarkRun.write_bytes(path, content)` guards verbatim JSONL/binary artifacts
and returns their SHA-256 and provenance for a separate manifest; it does not
inject a header into the bytes. SciFact ranking
files now use `{ "rankings": { ... }, "provenance": { ... } }`; readers also accept
the original plain ranking mappings. Model/data hashes remain the responsibility
of each runner and are recorded alongside this shared code/runtime provenance.

`make verify` runs backend and benchmark tests, both artifact verifiers, frontend
tests, and the production frontend build. Verification is read-only by default
and works on dirty trees:

```sh
.bench-venv/bin/python -m benchmarks.verify_v2_artifacts --input-dir docs/benchmarks-v2 --data-dir .benchmark-data
.bench-venv/bin/python -m benchmarks.verify_delivery_experiment --input-dir docs/benchmarks-delivery
```

An explicit `--output /path/to/receipt.json` writes a verification receipt. It does
not alter the historical result bundle. Corrupted-copy CLI tests ensure altered
metrics fail, while successful verification leaves historical receipts unchanged.
