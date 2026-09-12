#!/usr/bin/env python3
"""Package the full v3 result as deterministic gzip plus a compact summary."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.provenance import BenchmarkRun, add_provenance_argument  # noqa: E402

DEFAULT_INPUT = ROOT / ".benchmark-data" / "v3" / "raw" / "cross-domain-results.json"
OUTPUT_DIR = ROOT / "docs" / "benchmarks-v3"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def compact_dataset(dataset: dict) -> dict:
    matched = {}
    for context, cell in dataset["matched_contexts"].items():
        matched[context] = {
            "systems": {
                name: {key: value[key] for key in ("metrics", "latency", "fusion_only_latency") if key in value}
                for name, value in cell["systems"].items()
            },
            "vector_cache": cell["vector_cache"],
        }
    weak = dataset["weak_lexical_supplement"]
    return {
        key: dataset[key]
        for key in (
            "corpus_count",
            "test_query_count",
            "qrel_pairs",
            "canonical_content_sha256",
            "test_queries_sha256",
            "strong_lexical",
            "official_pyserini_multifield_sanity",
            "truncation",
        )
    } | {
        "matched_contexts": matched,
        "weak_lexical_supplement": {
            key: weak[key] for key in ("label", "source", "source_sha256")
        }
        | {
            "systems": {
                name: {key: value[key] for key in ("metrics", "latency") if key in value}
                for name, value in weak["systems"].items()
            }
        },
    }


def compact_result(full: dict, *, raw_sha256: str, raw_bytes: int, gzip_receipt: dict, gzip_name: str) -> dict:
    return {
        key: full[key]
        for key in ("schema_version", "created_at", "benchmark", "command", "runtime", "protocol", "sources", "models")
    } | {
        "datasets": {name: compact_dataset(value) for name, value in full["datasets"].items()},
        "inferential_families": full["inferential_families"],
        "full_rankings_artifact": {
            "path": gzip_name,
            "format": "gzip-compressed UTF-8 JSON; deterministic gzip mtime=0",
            "uncompressed_bytes": raw_bytes,
            "uncompressed_sha256": raw_sha256,
            "gzip_sha256": gzip_receipt["sha256"],
            "original_result_provenance": full["provenance"],
            "packaging_provenance": gzip_receipt["provenance"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    add_provenance_argument(parser)
    args = parser.parse_args()
    run = BenchmarkRun(
        allow_dirty=args.allow_dirty,
        sources=[Path(__file__), ROOT / "benchmarks" / "provenance.py"],
    )
    raw = args.input.read_bytes()
    full = json.loads(raw)
    compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    gzip_path = args.output_dir / "cross-domain-results.json.gz"
    gzip_receipt = run.write_bytes(gzip_path, compressed)
    summary = compact_result(
        full,
        raw_sha256=sha256_bytes(raw),
        raw_bytes=len(raw),
        gzip_receipt=gzip_receipt,
        gzip_name=gzip_path.name,
    )
    run.write_json(args.output_dir / "cross-domain-summary.json", summary)
    print(f"wrote {gzip_path} and compact summary", flush=True)


if __name__ == "__main__":
    main()
