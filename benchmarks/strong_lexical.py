#!/usr/bin/env python3
"""Build and run the fixed Pyserini/Anserini multi-field BEIR baseline.

This module deliberately does not evaluate qrels. The qrels file is read only to
select TEST query IDs; relevance grades stay outside indexing and retrieval.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.provenance import BenchmarkRun, add_provenance_argument  # noqa: E402

DATA_ROOT = ROOT / ".benchmark-data" / "v2"
OUTPUT_ROOT = ROOT / ".benchmark-data" / "v3" / "strong-lexical"
REQUIREMENTS = ROOT / "benchmarks" / "requirements-cross-domain-v3-lexical.txt"
PREDICTIONS = ROOT / "PREDICTIONS.md"

DATASETS = {
    "scifact": (5_183, 300),
    "nfcorpus": (3_633, 323),
    "fiqa": (57_638, 648),
}
BM25_K1 = 0.9
BM25_B = 0.4
FIELD_WEIGHTS = {"contents": 1.0, "title": 1.0}
INDEX_THREADS = 1
SEARCH_HITS = 1_000
RRF_POOL = 100


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def dataset_paths(name: str) -> tuple[Path, Path, Path]:
    folder = DATA_ROOT / name / name
    return folder / "corpus.jsonl", folder / "queries.jsonl", folder / "qrels" / "test.tsv"


def test_query_ids(qrels_path: Path) -> list[str]:
    """Return TEST IDs without retaining or exposing relevance grades."""
    with qrels_path.open(encoding="utf-8") as handle:
        next(handle)
        return sorted({line.split("\t", 1)[0] for line in handle if line.strip()})


def prepare_collection(name: str, output_dir: Path) -> tuple[Path, dict[str, str], list[str], int]:
    corpus_path, queries_path, qrels_path = dataset_paths(name)
    corpus = load_jsonl(corpus_path)
    queries = {str(row["_id"]): str(row["text"]) for row in load_jsonl(queries_path)}
    qids = test_query_ids(qrels_path)
    expected_docs, expected_queries = DATASETS[name]
    if len(corpus) != expected_docs or len(qids) != expected_queries:
        raise ValueError(
            f"{name}: expected {expected_docs}/{expected_queries} docs/queries, "
            f"got {len(corpus)}/{len(qids)}"
        )
    missing = [qid for qid in qids if qid not in queries]
    if missing:
        raise ValueError(f"{name}: qrels reference missing queries: {missing[:5]}")
    empty_documents = sum(
        not str(row.get("title", "")).strip() and not str(row.get("text", "")).strip()
        for row in corpus
    )

    collection_dir = output_dir / name / "collection"
    collection_dir.mkdir(parents=True, exist_ok=True)
    target = collection_dir / "documents.jsonl"
    temporary = target.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in corpus:
            # Pyserini's DefaultLuceneDocumentGenerator always indexes contents;
            # --fields title opts the second field into the index explicitly.
            value = {
                "id": str(row["_id"]),
                "contents": str(row.get("text", "")),
                "title": str(row.get("title", "")),
            }
            handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(temporary, target)
    return collection_dir, {qid: queries[qid] for qid in qids}, qids, empty_documents


def index_command(collection_dir: Path, index_dir: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pyserini.index.lucene",
        "--collection",
        "JsonCollection",
        "--input",
        str(collection_dir),
        "--index",
        str(index_dir),
        "--generator",
        "DefaultLuceneDocumentGenerator",
        "--threads",
        str(INDEX_THREADS),
        "--fields",
        "title",
        "--storePositions",
        "--storeDocvectors",
        "--storeRaw",
    ]


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(value for value in path.rglob("*") if value.is_file()):
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        with item.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def display_command(command: list[str]) -> list[str]:
    """Record a portable command without publishing local absolute paths."""
    output = list(command)
    output[0] = "python"
    for option in ("--input", "--index"):
        position = output.index(option) + 1
        path = Path(output[position]).resolve()
        output[position] = (
            path.relative_to(ROOT).as_posix()
            if path.is_relative_to(ROOT)
            else f"<EXTERNAL>/{path.name}"
        )
    return output


def build_index(collection_dir: Path, index_dir: Path, *, rebuild: bool) -> tuple[list[str], float, dict]:
    manifest_path = index_dir.parent / "index-manifest.json"
    command = index_command(collection_dir, index_dir)
    expected = {
        "collection_sha256": hash_file(collection_dir / "documents.jsonl"),
        "pyserini": importlib.metadata.version("pyserini"),
        "runner_sha256": hash_file(Path(__file__)),
        "command": display_command(command),
    }
    if rebuild and index_dir.exists():
        shutil.rmtree(index_dir)
        manifest_path.unlink(missing_ok=True)
    if index_dir.exists():
        if not manifest_path.exists():
            raise RuntimeError("existing index has no provenance manifest; pass --rebuild")
        manifest = json.loads(manifest_path.read_text())
        if any(manifest.get(key) != value for key, value in expected.items()):
            raise RuntimeError("existing index provenance differs from the frozen protocol; pass --rebuild")
        if manifest.get("index_tree_sha256") != tree_hash(index_dir):
            raise RuntimeError("existing index bytes differ from its manifest; pass --rebuild")
    if not index_dir.exists():
        started = time.perf_counter()
        subprocess.run(command, check=True, cwd=ROOT)
        elapsed = time.perf_counter() - started
        manifest = {**expected, "index_tree_sha256": tree_hash(index_dir)}
        temporary = manifest_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary, manifest_path)
    else:
        elapsed = 0.0
    if not index_dir.is_dir() or not any(index_dir.iterdir()):
        raise RuntimeError(f"Pyserini did not create a usable index: {index_dir}")
    return display_command(command), elapsed, manifest


def retrieve(index_dir: Path, queries: dict[str, str]) -> tuple[dict[str, list[str]], list[float], int]:
    from pyserini.search.lucene import LuceneSearcher

    searcher = LuceneSearcher(str(index_dir))
    indexed_documents = int(searcher.num_docs)
    searcher.set_bm25(BM25_K1, BM25_B)
    rankings: dict[str, list[str]] = {}
    latencies: list[float] = []
    try:
        for position, (qid, text) in enumerate(queries.items(), 1):
            started = time.perf_counter()
            # Ask for one spare result because official BEIR evaluation excludes
            # a result whose document ID equals the query ID.
            hits = searcher.search(text, k=SEARCH_HITS + 1, fields=FIELD_WEIGHTS)
            ranking = [str(hit.docid) for hit in hits if str(hit.docid) != qid][:SEARCH_HITS]
            latencies.append(time.perf_counter() - started)
            rankings[qid] = ranking
            if position % 100 == 0:
                print(f"strong lexical retrieval {position}/{len(queries)}", flush=True)
    finally:
        searcher.close()
    return rankings, latencies, indexed_documents


def java_version() -> str:
    completed = subprocess.run(
        ["java", "-version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True
    )
    return completed.stdout.strip()


def latency_summary(values: list[float]) -> dict:
    import numpy as np

    array = np.asarray(values, dtype=float)
    return {
        "samples": len(values),
        "p50_seconds": float(np.quantile(array, 0.5)) if len(array) else None,
        "p95_seconds": float(np.quantile(array, 0.95)) if len(array) else None,
        "mean_seconds": float(array.mean()) if len(array) else None,
        "total_seconds": float(array.sum()),
    }


def validate_rankings(rankings: dict[str, list[str]], qids: list[str]) -> None:
    if list(rankings) != qids:
        raise ValueError("ranking query IDs/order differ from frozen TEST query IDs")
    for qid, docs in rankings.items():
        if qid in docs:
            raise ValueError(f"self document not excluded for {qid}")
        if len(docs) != len(set(docs)):
            raise ValueError(f"duplicate document in ranking for {qid}")
        if len(docs) > SEARCH_HITS:
            raise ValueError(f"ranking exceeds {SEARCH_HITS} for {qid}")


def run_dataset(name: str, output_root: Path, *, rebuild: bool) -> dict:
    collection_dir, queries, qids, empty_documents = prepare_collection(name, output_root)
    index_dir = output_root / name / "index"
    command, index_seconds, index_manifest = build_index(collection_dir, index_dir, rebuild=rebuild)
    rankings, latencies, indexed_documents = retrieve(index_dir, queries)
    validate_rankings(rankings, qids)
    if indexed_documents != DATASETS[name][0] - empty_documents:
        raise ValueError(
            f"{name}: index has {indexed_documents} documents; expected "
            f"{DATASETS[name][0] - empty_documents} after excluding empty rows"
        )
    return {
        "dataset": name,
        "corpus_count": DATASETS[name][0],
        "indexed_document_count": indexed_documents,
        "empty_document_count": empty_documents,
        "test_query_count": len(qids),
        "rankings_top1000": rankings,
        "rankings_top100_for_rrf": {qid: docs[:RRF_POOL] for qid, docs in rankings.items()},
        "search_latency_seconds": dict(zip(qids, latencies, strict=True)),
        "index_seconds_this_run": index_seconds,
        "index_manifest": index_manifest,
        "search_latency": latency_summary(latencies),
        "protocol": {
            "engine": "Pyserini/Anserini/Lucene",
            "pyserini": importlib.metadata.version("pyserini"),
            "java": java_version(),
            "document_generator": "DefaultLuceneDocumentGenerator",
            "analyzer": "DefaultEnglishAnalyzer: StandardTokenizer, English possessive, lowercase, Lucene English stop set, Porter stemming",
            "bm25": {"k1": BM25_K1, "b": BM25_B},
            "fields": FIELD_WEIGHTS,
            "index_threads": INDEX_THREADS,
            "search_hits": SEARCH_HITS,
            "rrf_pool": RRF_POOL,
            "self_document_exclusion": True,
            "index_command": command,
            "qrels_isolation": "qrels supply TEST query IDs only; relevance grades are not loaded by this runner",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--datasets", default="scifact,nfcorpus,fiqa")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--rebuild", action="store_true")
    add_provenance_argument(parser)
    args = parser.parse_args()
    names = [name.strip() for name in args.datasets.split(",") if name.strip()]
    unknown = set(names) - DATASETS.keys()
    if unknown:
        raise SystemExit(f"unknown datasets: {sorted(unknown)}")

    run = BenchmarkRun(
        allow_dirty=args.allow_dirty,
        requirements=REQUIREMENTS,
        predictions=PREDICTIONS,
        sources=[Path(__file__), ROOT / "benchmarks" / "provenance.py"],
    )
    for name in names:
        result = run_dataset(name, args.output_dir, rebuild=args.rebuild)
        output = args.output_dir / f"{name}-rankings.json"
        run.write_json(output, result)
        print(f"wrote {output}", flush=True)


if __name__ == "__main__":
    main()
