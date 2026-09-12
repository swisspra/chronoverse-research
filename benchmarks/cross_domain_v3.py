#!/usr/bin/env python3
"""Preregistered strong-lexical and matched-length BEIR benchmark.

The runner consumes retrieval-only Pyserini rankings, creates/reuses dense
vectors with explicit 256/512-token cells, and evaluates only after every
ranking is frozen. No qrel grade reaches indexing, embedding, or retrieval.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import json
import os
import platform
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.metrics import latency_summary, reciprocal_rank_fusion  # noqa: E402
from benchmarks.provenance import BenchmarkRun, add_provenance_argument  # noqa: E402
from benchmarks.statistics import comparison_family  # noqa: E402

V2_DATA = ROOT / ".benchmark-data" / "v2"
V3_DATA = ROOT / ".benchmark-data" / "v3"
LEXICAL_ROOT = V3_DATA / "strong-lexical"
MODEL_CACHE = ROOT / ".model-cache" / "mps"
OUTPUT = ROOT / "docs" / "benchmarks-v3" / "cross-domain-results.json"
REQUIREMENTS = ROOT / "benchmarks" / "requirements-cross-domain-v3.txt"
PREDICTIONS = ROOT / "PREDICTIONS.md"
V2_RESULT = ROOT / "docs" / "benchmarks-v2" / "cross-domain-results.json"
V2_EXECUTED_SOURCE = ROOT / "docs" / "benchmarks-v2" / "source" / "cross-domain" / "cross_domain.py"
V2_EXECUTED_SOURCE_SHA256 = "1c5d63d12c06e85478ce86887734030a36c644db5c92060b7653c355f34f1f31"
APPROVED_LEGACY_EMBEDDING_SOURCES = {
    "dd1494829d52ef44774f4f310178c47fd74a8370db96b5d4c8ae14e7a9d9d6ee": (
        "frozen commit 7c2eed4 initial v3 run; subsequent changes only add output metadata, "
        "path redaction, and verification"
    ),
}

SEED = 20_260_912
SAMPLES = 10_000
RRF_K = 60
RANKING_LIMIT = 100
CONTEXT_LENGTHS = (256, 512)
QUERY_PREFIX_BGE = "Represent this sentence for searching relevant passages: "

DATASETS = {
    "scifact": {"corpus": 5_183, "queries": 300, "pyserini_multifield_ndcg10": 0.665},
    "nfcorpus": {"corpus": 3_633, "queries": 323, "pyserini_multifield_ndcg10": 0.325},
    "fiqa": {"corpus": 57_638, "queries": 648, "pyserini_multifield_ndcg10": 0.236},
}
MODELS = {
    "minilm": {
        "name": "sentence-transformers/all-MiniLM-L6-v2",
        "path": MODEL_CACHE / "models--sentence-transformers--all-MiniLM-L6-v2",
        "revision": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
        "query_prefix": "",
        "dimensions": 384,
        "documented_training_tokens": 256,
    },
    "bge": {
        "name": "BAAI/bge-small-en-v1.5",
        "path": MODEL_CACHE / "models--BAAI--bge-small-en-v1.5",
        "revision": "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
        "query_prefix": QUERY_PREFIX_BGE,
        "dimensions": 384,
        "documented_training_tokens": 512,
    },
}
V2_REUSE_LENGTH = {"minilm": 256, "bge": 512}
_EMBEDDERS: dict[tuple[str, int], object] = {}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file() and ".lock" not in p.name):
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        with item.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, path)


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def canonical_text(row: dict) -> str:
    return "\n".join(
        part.strip() for part in (str(row.get("title", "")), str(row.get("text", ""))) if part.strip()
    )


def stable_rows_hash(ids: list[str], texts: list[str]) -> str:
    digest = hashlib.sha256()
    for row_id, text in zip(ids, texts, strict=True):
        digest.update(row_id.encode())
        digest.update(b"\0")
        digest.update(text.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def load_dataset(name: str) -> dict:
    folder = V2_DATA / name / name
    corpus = load_jsonl(folder / "corpus.jsonl")
    queries = {str(row["_id"]): str(row["text"]) for row in load_jsonl(folder / "queries.jsonl")}
    qrels: dict[str, dict[str, int]] = defaultdict(dict)
    with (folder / "qrels" / "test.tsv").open(encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            qid, docid, grade = line.rstrip("\n").split("\t")
            qrels[qid][docid] = int(grade)
    qids = sorted(qrels)
    doc_ids = [str(row["_id"]) for row in corpus]
    texts = [canonical_text(row) for row in corpus]
    query_texts = [queries[qid] for qid in qids]
    spec = DATASETS[name]
    if (len(doc_ids), len(qids)) != (spec["corpus"], spec["queries"]):
        raise ValueError(f"{name}: full-corpus counts changed")
    return {
        "doc_ids": doc_ids,
        "texts": texts,
        "query_ids": qids,
        "queries": query_texts,
        "qrels": dict(qrels),
        "content_sha256": stable_rows_hash(doc_ids, texts),
        "queries_sha256": stable_rows_hash(qids, query_texts),
    }


def normalize_rows(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    np.divide(matrix, np.maximum(norms, 1e-12), out=matrix)
    return matrix


def validate_vectors(matrix: np.ndarray, rows: int, dimensions: int) -> None:
    if matrix.shape != (rows, dimensions) or matrix.dtype != np.float32:
        raise ValueError(f"invalid vector shape/dtype: {matrix.shape}/{matrix.dtype}")
    for offset in range(0, rows, 4096):
        block = np.asarray(matrix[offset : offset + 4096])
        if not np.isfinite(block).all():
            raise ValueError("vector cache contains a non-finite value")
        if not np.allclose(np.linalg.norm(block, axis=1), 1.0, atol=2e-5):
            raise ValueError("vector cache contains a non-unit row")


def model_tree_hash(model_key: str) -> str:
    path = MODELS[model_key]["path"]
    if not path.is_dir():
        raise FileNotFoundError(f"missing frozen model cache: {path}")
    return tree_hash(path)


def reuse_v2_vectors(
    dataset: str, model_key: str, kind: str, ids: list[str], texts: list[str], context: int
) -> tuple[np.ndarray, dict] | None:
    if V2_REUSE_LENGTH[model_key] != context:
        return None
    if sha256(V2_EXECUTED_SOURCE) != V2_EXECUTED_SOURCE_SHA256:
        raise ValueError("v2 executed source archive changed; legacy vectors cannot be attributed")
    array_path = V2_DATA / f"{dataset}-{model_key}-{kind}.npy"
    meta_path = V2_DATA / f"{dataset}-{model_key}-{kind}.meta.json"
    meta = json.loads(meta_path.read_text())
    spec = MODELS[model_key]
    prefix = spec["query_prefix"] if kind == "queries" else ""
    expected = {
        "dataset": dataset,
        "model": spec["name"],
        "kind": kind,
        "rows": len(ids),
        "dimensions": spec["dimensions"],
        "content_sha256": stable_rows_hash(ids, texts),
        "query_prefix": prefix,
        "normalized": True,
        "dtype": "float32",
        "backend": "mps-fp32",
        "precision": "float32",
        "model_cache_tree_sha256": model_tree_hash(model_key),
    }
    if any(meta.get(key) != value for key, value in expected.items()):
        raise ValueError(f"{dataset}/{model_key}/{kind}: v2 cache provenance mismatch")
    if meta.get("array_sha256") != sha256(array_path):
        raise ValueError(f"{dataset}/{model_key}/{kind}: v2 array hash mismatch")
    matrix = np.load(array_path, mmap_mode="r")
    validate_vectors(matrix, len(ids), spec["dimensions"])
    return matrix, {
        **meta,
        "context_tokens": context,
        "cache_reused": True,
        "reuse_source": str(V2_EXECUTED_SOURCE.relative_to(ROOT)),
        "reuse_source_sha256": V2_EXECUTED_SOURCE_SHA256,
        "legacy_meta_sha256": sha256(meta_path),
        "reuse_limitation": "v2 metadata omitted explicit context length; frozen executed source sets this exact model length",
    }


def get_embedder(model_key: str, context: int):
    cache_key = (model_key, context)
    if cache_key not in _EMBEDDERS:
        from sentence_transformers import SentenceTransformer

        spec = MODELS[model_key]
        snapshot = spec["path"] / "snapshots" / spec["revision"]
        if not snapshot.is_dir():
            raise FileNotFoundError(f"missing pinned model snapshot: {snapshot}")
        model = SentenceTransformer(str(snapshot), device="mps", local_files_only=True)
        model.max_seq_length = context
        _EMBEDDERS[cache_key] = model
    return _EMBEDDERS[cache_key]


def embedding_code_fingerprint() -> str:
    functions = (canonical_text, stable_rows_hash, normalize_rows, get_embedder, embed_vectors)
    source = "\n".join(inspect.getsource(function) for function in functions)
    parameters = {
        key: {
            "name": value["name"],
            "revision": value["revision"],
            "query_prefix": value["query_prefix"],
            "dimensions": value["dimensions"],
        }
        for key, value in MODELS.items()
    }
    payload = source + "\n" + json.dumps(parameters, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def validate_embedding_code(meta: dict) -> dict:
    fingerprint = meta.get("embedding_code_fingerprint")
    if fingerprint is not None:
        if fingerprint != embedding_code_fingerprint():
            raise ValueError("dense cache embedding code fingerprint is not current")
        return {"method": "embedding_code_fingerprint", "accepted": fingerprint}
    source_hash = meta.get("embedding_source_sha256")
    current_hash = sha256(Path(__file__))
    if source_hash == current_hash:
        return {"method": "whole_source_sha256", "accepted": source_hash}
    if source_hash in APPROVED_LEGACY_EMBEDDING_SOURCES:
        return {
            "method": "reviewed_legacy_whole_source_sha256",
            "accepted": source_hash,
            "rationale": APPROVED_LEGACY_EMBEDDING_SOURCES[source_hash],
        }
    raise ValueError("dense cache came from an unapproved embedding source")


def dense_cache_paths(dataset: str, model_key: str, context: int, kind: str) -> tuple[Path, Path, Path, Path]:
    folder = V3_DATA / "dense"
    stem = f"{dataset}-{model_key}-{context}-{kind}"
    return (
        folder / f"{stem}.npy",
        folder / f"{stem}.meta.json",
        folder / f"{stem}.partial.npy",
        folder / f"{stem}.partial.meta.json",
    )


def embed_vectors(
    *, dataset: str, model_key: str, context: int, kind: str, ids: list[str], texts: list[str], rebuild: bool
) -> tuple[np.ndarray, dict]:
    reused = reuse_v2_vectors(dataset, model_key, kind, ids, texts, context)
    if reused is not None and not rebuild:
        print(f"[{dataset}] reuse v2 {model_key}@{context} {kind}", flush=True)
        return reused

    spec = MODELS[model_key]
    prefix = spec["query_prefix"] if kind == "queries" else ""
    array_path, meta_path, partial_path, partial_meta_path = dense_cache_paths(
        dataset, model_key, context, kind
    )
    array_path.parent.mkdir(parents=True, exist_ok=True)
    packages = {
        name: importlib.metadata.version(name)
        for name in ("torch", "sentence-transformers", "transformers")
    }
    expected = {
        "dataset": dataset,
        "model": spec["name"],
        "model_revision": spec["revision"],
        "kind": kind,
        "rows": len(ids),
        "dimensions": spec["dimensions"],
        "content_sha256": stable_rows_hash(ids, texts),
        "query_prefix": prefix,
        "context_tokens": context,
        "add_special_tokens": True,
        "normalized": True,
        "dtype": "float32",
        "backend": "sentence-transformers-mps-fp32",
        "model_cache_tree_sha256": model_tree_hash(model_key),
        "backend_packages": packages,
    }
    if not rebuild and array_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if all(meta.get(key) == value for key, value in expected.items()) and meta.get("array_sha256") == sha256(array_path):
            code_validation = validate_embedding_code(meta)
            matrix = np.load(array_path, mmap_mode="r")
            validate_vectors(matrix, len(ids), spec["dimensions"])
            return matrix, {
                **meta,
                "cache_reused": True,
                "elapsed_seconds_this_run": 0.0,
                "reuse_source_validation": code_validation,
            }

    start = 0
    prior_seconds = 0.0
    matrix = None
    if not rebuild and partial_path.exists() and partial_meta_path.exists():
        partial_meta = json.loads(partial_meta_path.read_text())
        if all(partial_meta.get(key) == value for key, value in expected.items()):
            validate_embedding_code(partial_meta)
            matrix = np.lib.format.open_memmap(partial_path, mode="r+")
            start = int(partial_meta["completed_rows"])
            prior_seconds = float(partial_meta["elapsed_seconds"])
    if matrix is None:
        partial_path.unlink(missing_ok=True)
        partial_meta_path.unlink(missing_ok=True)
        matrix = np.lib.format.open_memmap(
            partial_path, mode="w+", dtype=np.float32, shape=(len(ids), spec["dimensions"])
        )
    embedder = get_embedder(model_key, context)
    inputs = [(prefix + value) if prefix else value for value in texts[start:]]
    started = time.perf_counter()
    completed = start
    for offset in range(0, len(inputs), 128):
        batch = embedder.encode(
            inputs[offset : offset + 128],
            batch_size=32,
            convert_to_numpy=True,
            normalize_embeddings=False,
            show_progress_bar=False,
            device="mps",
        )
        end = start + offset + len(batch)
        matrix[start + offset : end] = batch
        completed = end
        matrix.flush()
        atomic_json(
            partial_meta_path,
            {
                **expected,
                "embedding_source_sha256": sha256(Path(__file__)),
                "embedding_code_fingerprint": embedding_code_fingerprint(),
                "completed_rows": completed,
                "elapsed_seconds": prior_seconds + time.perf_counter() - started,
                "updated_at": now(),
            },
        )
        if completed % 1024 < 128:
            print(f"[{dataset}] {model_key}@{context} {kind} {completed}/{len(ids)}", flush=True)
    if completed != len(ids):
        raise RuntimeError(f"embedded {completed}, expected {len(ids)}")
    elapsed_this_run = time.perf_counter() - started
    for offset in range(0, len(ids), 4096):
        matrix[offset : offset + 4096] = normalize_rows(np.asarray(matrix[offset : offset + 4096]))
    matrix.flush()
    del matrix
    os.replace(partial_path, array_path)
    partial_meta_path.unlink(missing_ok=True)
    meta = {
        **expected,
        "embedding_source_sha256": sha256(Path(__file__)),
        "embedding_code_fingerprint": embedding_code_fingerprint(),
        "index_seconds": prior_seconds + elapsed_this_run,
        "elapsed_seconds_this_run": elapsed_this_run,
        "array_sha256": sha256(array_path),
        "created_at": now(),
        "cache_reused": False,
    }
    atomic_json(meta_path, meta)
    matrix = np.load(array_path, mmap_mode="r")
    validate_vectors(matrix, len(ids), spec["dimensions"])
    return matrix, meta


def token_lengths(tokenizer, texts: list[str], prefix: str = "", batch_size: int = 512) -> list[int]:
    lengths: list[int] = []
    for offset in range(0, len(texts), batch_size):
        values = [prefix + text for text in texts[offset : offset + batch_size]]
        encoded = tokenizer(
            values,
            add_special_tokens=True,
            truncation=False,
            padding=False,
            return_length=True,
            verbose=False,
        )
        if "length" in encoded:
            lengths.extend(int(value) for value in encoded["length"])
        else:
            lengths.extend(len(value) for value in encoded["input_ids"])
    return lengths


def summarize_lengths(lengths: list[int]) -> dict:
    values = np.asarray(lengths, dtype=int)
    return {
        "count": len(lengths),
        "p50": float(np.quantile(values, 0.50)),
        "p95": float(np.quantile(values, 0.95)),
        "p99": float(np.quantile(values, 0.99)),
        "max": int(values.max()),
        "over_256": int(np.sum(values > 256)),
        "over_256_fraction": float(np.mean(values > 256)),
        "over_512": int(np.sum(values > 512)),
        "over_512_fraction": float(np.mean(values > 512)),
    }


def truncation_statistics(model_key: str, documents: list[str], queries: list[str]) -> dict:
    model = get_embedder(model_key, MODELS[model_key]["documented_training_tokens"])
    tokenizer = model.tokenizer
    prefix = MODELS[model_key]["query_prefix"]
    return {
        "tokenizer": MODELS[model_key]["name"],
        "model_revision": MODELS[model_key]["revision"],
        "add_special_tokens": True,
        "query_prefix_included": prefix,
        "documents": summarize_lengths(token_lengths(tokenizer, documents)),
        "queries": summarize_lengths(token_lengths(tokenizer, queries, prefix)),
    }


def top_indices(scores: np.ndarray, doc_ids: list[str], limit: int) -> list[int]:
    count = min(limit, len(scores))
    candidates = np.argpartition(scores, -count)[-count:]
    threshold = float(np.min(scores[candidates]))
    above = np.flatnonzero(scores > threshold).tolist()
    tied = np.flatnonzero(scores == threshold).tolist()
    above.sort(key=lambda index: (-float(scores[index]), doc_ids[index]))
    tied.sort(key=lambda index: doc_ids[index])
    return (above + tied[: count - len(above)])[:count]


def dense_rankings(
    documents: np.ndarray, queries: np.ndarray, doc_ids: list[str], query_ids: list[str]
) -> tuple[dict[str, list[str]], list[float]]:
    output: dict[str, list[str]] = {}
    latencies: list[float] = []
    positions = {docid: index for index, docid in enumerate(doc_ids)}
    for qid, vector in zip(query_ids, queries, strict=True):
        started = time.perf_counter()
        scores = np.asarray(documents @ vector)
        if qid in positions:
            scores[positions[qid]] = -np.inf
        indices = top_indices(scores, doc_ids, RANKING_LIMIT)
        latencies.append(time.perf_counter() - started)
        output[qid] = [doc_ids[index] for index in indices]
    return output, latencies


def linear_metrics_for_query(ranked_ids: list[str], qrels: dict[str, int]) -> dict[str, float]:
    relevant = {docid: float(grade) for docid, grade in qrels.items() if grade > 0}
    ranked = list(dict.fromkeys(ranked_ids))
    gains = [relevant.get(docid, 0.0) for docid in ranked[:10]]
    dcg = sum(gain / np.log2(rank + 2) for rank, gain in enumerate(gains))
    ideal = sum(
        gain / np.log2(rank + 2)
        for rank, gain in enumerate(sorted(relevant.values(), reverse=True)[:10])
    )
    return {
        "ndcg@10": float(dcg / ideal if ideal else 0.0),
        "recall@10": len(set(ranked[:10]) & relevant.keys()) / len(relevant) if relevant else 0.0,
        "mrr@10": next((1 / rank for rank, docid in enumerate(ranked[:10], 1) if docid in relevant), 0.0),
    }


def evaluate(rankings: dict[str, list[str]], qrels: dict[str, dict[str, int]], latencies=None) -> dict:
    per_query = {qid: linear_metrics_for_query(rankings.get(qid, []), labels) for qid, labels in qrels.items()}
    metrics = {
        name: float(np.mean([row[name] for row in per_query.values()]))
        for name in ("ndcg@10", "recall@10", "mrr@10")
    }
    result = {"metrics": {**metrics, "query_count": len(per_query)}, "rankings": rankings}
    if latencies is not None:
        result["latency"] = latency_summary(latencies)
    return result


def load_strong_lexical(name: str, query_ids: list[str]) -> tuple[dict[str, list[str]], list[float], dict]:
    path = LEXICAL_ROOT / f"{name}-rankings.json"
    value = json.loads(path.read_text())
    protocol = value["protocol"]
    provenance = value.get("provenance", {})
    expected = {
        "bm25": {"k1": 0.9, "b": 0.4},
        "fields": {"contents": 1.0, "title": 1.0},
        "rrf_pool": 100,
        "self_document_exclusion": True,
    }
    if any(protocol.get(key) != expected_value for key, expected_value in expected.items()):
        raise ValueError(f"{name}: strong lexical protocol mismatch")
    expected_source = sha256(ROOT / "benchmarks" / "strong_lexical.py")
    if provenance.get("source_sha256", {}).get("benchmarks/strong_lexical.py") != expected_source:
        raise ValueError(f"{name}: strong lexical source provenance mismatch")
    if provenance.get("predictions_sha256") != sha256(PREDICTIONS) or not provenance.get("predictions_committed_exactly"):
        raise ValueError(f"{name}: strong lexical prediction provenance mismatch")
    rankings = value["rankings_top100_for_rrf"]
    if list(rankings) != query_ids:
        raise ValueError(f"{name}: lexical ranking query IDs changed")
    latency_map = value["search_latency_seconds"]
    latencies = [float(latency_map[qid]) for qid in query_ids]
    return rankings, latencies, {
        "path": str(path.relative_to(ROOT)),
        "provenance": provenance,
        "protocol": protocol,
        "corpus_input_count": value["corpus_count"],
        "indexed_document_count": value["indexed_document_count"],
        "empty_document_count": value["empty_document_count"],
    }


def load_weak_v2(name: str, query_ids: list[str]) -> dict:
    value = json.loads(V2_RESULT.read_text())
    dataset = value["datasets"][name]
    systems = dataset["systems"]
    output = {}
    for system_name in ("bm25", "bge_dense", "bge_hybrid_rrf"):
        ranking = systems[system_name]["rankings"]
        if list(ranking) != query_ids:
            raise ValueError(f"{name}: v2 {system_name} qids changed")
        output[system_name] = systems[system_name]
    return {
        "label": "historical weak regex-token rank_bm25 baseline; supplementary only",
        "source": str(V2_RESULT.relative_to(ROOT)),
        "source_sha256": sha256(V2_RESULT),
        "systems": output,
    }


def fuse(
    runs: list[dict[str, list[str]]], component_latencies: list[list[float]], query_ids: list[str]
) -> tuple[dict[str, list[str]], list[float], list[float]]:
    output, total, fusion_only = {}, [], []
    for index, qid in enumerate(query_ids):
        started = time.perf_counter()
        output[qid] = reciprocal_rank_fusion([run[qid] for run in runs], k=RRF_K, limit=RANKING_LIMIT)
        fusion = time.perf_counter() - started
        fusion_only.append(fusion)
        total.append(sum(component[index] for component in component_latencies) + fusion)
    return output, total, fusion_only


def run_dataset(name: str, *, rebuild: bool) -> dict:
    data = load_dataset(name)
    qids, qrels = data["query_ids"], data["qrels"]
    strong, strong_latency, strong_meta = load_strong_lexical(name, qids)
    weak = load_weak_v2(name, qids)
    vectors, vector_meta, dense_runs, dense_latency = {}, {}, {}, {}
    for context in CONTEXT_LENGTHS:
        vectors[context], vector_meta[context], dense_runs[context], dense_latency[context] = {}, {}, {}, {}
        for model_key in MODELS:
            docs, doc_meta = embed_vectors(
                dataset=name,
                model_key=model_key,
                context=context,
                kind="documents",
                ids=data["doc_ids"],
                texts=data["texts"],
                rebuild=rebuild,
            )
            queries, query_meta = embed_vectors(
                dataset=name,
                model_key=model_key,
                context=context,
                kind="queries",
                ids=qids,
                texts=data["queries"],
                rebuild=rebuild,
            )
            dense_runs[context][model_key], dense_latency[context][model_key] = dense_rankings(
                docs, queries, data["doc_ids"], qids
            )
            vector_meta[context][model_key] = {"documents": doc_meta, "queries": query_meta}

    matched = {}
    for context in CONTEXT_LENGTHS:
        minilm_hybrid, minilm_total, minilm_fusion = fuse(
            [strong, dense_runs[context]["minilm"]],
            [strong_latency, dense_latency[context]["minilm"]],
            qids,
        )
        bge_hybrid, bge_total, bge_fusion = fuse(
            [strong, dense_runs[context]["bge"]],
            [strong_latency, dense_latency[context]["bge"]],
            qids,
        )
        three_way, three_total, three_fusion = fuse(
            [strong, dense_runs[context]["minilm"], dense_runs[context]["bge"]],
            [strong_latency, dense_latency[context]["minilm"], dense_latency[context]["bge"]],
            qids,
        )
        systems = {
            "strong_bm25": evaluate(strong, qrels, strong_latency),
            "minilm_dense": evaluate(dense_runs[context]["minilm"], qrels, dense_latency[context]["minilm"]),
            "bge_dense": evaluate(dense_runs[context]["bge"], qrels, dense_latency[context]["bge"]),
            "minilm_hybrid_rrf": evaluate(minilm_hybrid, qrels, minilm_total),
            "bge_hybrid_rrf": evaluate(bge_hybrid, qrels, bge_total),
            "three_way_rrf": evaluate(three_way, qrels, three_total),
        }
        systems["minilm_hybrid_rrf"]["fusion_only_latency"] = latency_summary(minilm_fusion)
        systems["bge_hybrid_rrf"]["fusion_only_latency"] = latency_summary(bge_fusion)
        systems["three_way_rrf"]["fusion_only_latency"] = latency_summary(three_fusion)
        matched[str(context)] = {"systems": systems, "vector_cache": vector_meta[context]}

    strong_ndcg = matched["256"]["systems"]["strong_bm25"]["metrics"]["ndcg@10"]
    expected_ndcg = DATASETS[name]["pyserini_multifield_ndcg10"]
    return {
        "corpus_count": len(data["doc_ids"]),
        "test_query_count": len(qids),
        "qrel_pairs": sum(len(rows) for rows in qrels.values()),
        "canonical_content_sha256": data["content_sha256"],
        "test_queries_sha256": data["queries_sha256"],
        "strong_lexical": strong_meta,
        "official_pyserini_multifield_sanity": {
            "published_ndcg@10": expected_ndcg,
            "observed_ndcg@10": strong_ndcg,
            "difference": strong_ndcg - expected_ndcg,
            "role": "post-freeze reproduction check, never a tuning target",
        },
        "truncation": {
            model: truncation_statistics(model, data["texts"], data["queries"]) for model in MODELS
        },
        "matched_contexts": matched,
        "weak_lexical_supplement": weak,
    }


def ndcg_values(system: dict, qrels: dict[str, dict[str, int]], qids: list[str]) -> list[float]:
    return [linear_metrics_for_query(system["rankings"][qid], qrels[qid])["ndcg@10"] for qid in qids]


def inferential_families(datasets: dict[str, dict]) -> dict:
    matched_families = {}
    for context in CONTEXT_LENGTHS:
        contrasts = {}
        for name in DATASETS:
            qrels = load_dataset(name)["qrels"]
            qids = sorted(qrels)
            systems = datasets[name]["matched_contexts"][str(context)]["systems"]
            reference = ndcg_values(systems["minilm_hybrid_rrf"], qrels, qids)
            for system_name, system in systems.items():
                if system_name == "minilm_hybrid_rrf":
                    continue
                contrasts[f"{name}/{system_name}-minus-minilm_hybrid_rrf"] = (
                    ndcg_values(system, qrels, qids),
                    reference,
                )
        matched_families[str(context)] = {
            "reference": "minilm_hybrid_rrf at same context length",
            "hypotheses": len(contrasts),
            "self_reference_display_only": {"mean_difference": 0.0, "p_value": 1.0},
            "comparisons": comparison_family(contrasts, samples=SAMPLES, seed=SEED),
        }

    length_contrasts = {}
    for name in DATASETS:
        qrels = load_dataset(name)["qrels"]
        qids = sorted(qrels)
        for model in ("minilm_dense", "bge_dense"):
            long_system = datasets[name]["matched_contexts"]["512"]["systems"][model]
            short_system = datasets[name]["matched_contexts"]["256"]["systems"][model]
            length_contrasts[f"{name}/{model}@512-minus-@256"] = (
                ndcg_values(long_system, qrels, qids),
                ndcg_values(short_system, qrels, qids),
            )

    fiqa_qrels = load_dataset("fiqa")["qrels"]
    fiqa_qids = sorted(fiqa_qrels)
    fiqa = datasets["fiqa"]
    fiqa_contrasts = {}
    for context in CONTEXT_LENGTHS:
        systems = fiqa["matched_contexts"][str(context)]["systems"]
        fiqa_contrasts[f"strong_bm25@{context}/bge_hybrid-minus-bge_dense"] = (
            ndcg_values(systems["bge_hybrid_rrf"], fiqa_qrels, fiqa_qids),
            ndcg_values(systems["bge_dense"], fiqa_qrels, fiqa_qids),
        )
    old = fiqa["weak_lexical_supplement"]["systems"]
    fiqa_contrasts["historical_weak_bm25/bge_hybrid-minus-bge_dense"] = (
        ndcg_values(old["bge_hybrid_rrf"], fiqa_qrels, fiqa_qids),
        ndcg_values(old["bge_dense"], fiqa_qrels, fiqa_qids),
    )
    return {
        "primary_matched_context_families": matched_families,
        "length_ablation_family": {
            "hypotheses": len(length_contrasts),
            "comparisons": comparison_family(length_contrasts, samples=SAMPLES, seed=SEED),
        },
        "fiqa_hybrid_minus_bge_confirmatory_family": {
            "hypotheses": len(fiqa_contrasts),
            "comparisons": comparison_family(fiqa_contrasts, samples=SAMPLES, seed=SEED),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--datasets", default="scifact,nfcorpus,fiqa")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--rebuild", action="store_true")
    add_provenance_argument(parser)
    args = parser.parse_args()
    names = [name.strip() for name in args.datasets.split(",") if name.strip()]
    if names != list(DATASETS):
        raise SystemExit("the confirmatory run requires scifact,nfcorpus,fiqa in frozen order")
    run = BenchmarkRun(
        allow_dirty=args.allow_dirty,
        requirements=REQUIREMENTS,
        predictions=PREDICTIONS,
        sources=[Path(__file__), ROOT / "benchmarks" / "strong_lexical.py", ROOT / "benchmarks" / "metrics.py", ROOT / "benchmarks" / "statistics.py", ROOT / "benchmarks" / "provenance.py"],
    )
    datasets = {name: run_dataset(name, rebuild=args.rebuild) for name in names}
    result = {
        "schema_version": 1,
        "created_at": now(),
        "benchmark": "full-corpus BEIR strong lexical and matched 256/512-token retrieval",
        "command": ".bench-mps-venv/bin/python benchmarks/cross_domain_v3.py",
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "dense_backend": "SentenceTransformers MPS FP32",
            "paid_api_calls": 0,
        },
        "protocol": {
            "ranking_limit": RANKING_LIMIT,
            "rrf_k": RRF_K,
            "ndcg_gain": "linear qrel gain matching trec_eval/BEIR ndcg_cut",
            "context_lengths": list(CONTEXT_LENGTHS),
            "primary_context": 256,
            "matched_512_role": "predeclared sensitivity family; MiniLM@512 exceeds its documented training/default length",
            "exact_dense_search": "L2-normalized vectors, exhaustive dot product, deterministic document-ID tie break",
            "canonical_dense_text": "non-empty title, newline, passage",
            "strong_lexical_fields": "title and passage indexed separately at equal weight",
            "rrf_candidate_pool": 100,
            "qrels_isolation": "grades enter only evaluation after all rankings are frozen",
            "bootstrap_samples": SAMPLES,
            "seed": SEED,
            "inferential_metric": "nDCG@10; recall@10 and MRR@10 are descriptive",
            "multiple_comparisons": "Holm-adjusted paired permutation p-values; separately labelled Bonferroni simultaneous paired-bootstrap intervals",
            "timing_limitation": "shared-machine observational timing; reused and fresh vector cells are not causal latency comparisons",
        },
        "sources": {
            "pyserini_beir_2cr": "https://castorini.github.io/pyserini/2cr/beir.html",
            "anserini_default_english_analyzer": "https://github.com/castorini/anserini/blob/master/src/main/java/io/anserini/analysis/DefaultEnglishAnalyzer.java",
            "beir_multifield_resource_paper": "https://ehsk.github.io/assets/pdf/SIGIR_2024__BEIR_Resource.pdf",
            "minilm": "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2",
            "bge": "https://huggingface.co/BAAI/bge-small-en-v1.5",
        },
        "models": {
            key: {
                **spec,
                "path": str(spec["path"].relative_to(ROOT)),
                "artifact_tree_sha256": model_tree_hash(key),
            }
            for key, spec in MODELS.items()
        },
        "datasets": datasets,
        "inferential_families": inferential_families(datasets),
    }
    run.write_json(args.output, result)
    print(f"wrote {args.output}", flush=True)


if __name__ == "__main__":
    main()
