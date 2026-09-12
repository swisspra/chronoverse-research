#!/usr/bin/env python3
"""Reproducible full-corpus BEIR retrieval benchmark.

Test qrels select query IDs. Relevance values are used only to evaluate completed
rankings; they do not enter document scoring or parameter selection.
Dense-vector caches and completed dataset phases make interrupted runs resumable.
"""
from __future__ import annotations
from benchmarks.provenance import BenchmarkRun, add_provenance_argument
import argparse

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks.metrics import (  # noqa: E402
    latency_summary,
    paired_bootstrap_difference,
    reciprocal_rank_fusion,
)

DATA_DIR = ROOT / ".benchmark-data" / "v2"
MODEL_CACHE = ROOT / ".model-cache"
OUTPUT = ROOT / "docs" / "benchmarks-v2" / "cross-domain-results.json"
TOKEN_RE = re.compile(r"\w+", re.UNICODE)
QUERY_PREFIX_BGE = "Represent this sentence for searching relevant passages: "
RRF_K = 60
RANKING_LIMIT = 100
BOOTSTRAP_SAMPLES = 10_000
SEED = 20_260_912

DATASETS = {
    "scifact": {
        "archive_url": "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip",
        "md5": "5f7d1de60b170fc8027bb7898e2efca1",
        "sha256": "536e14446a0ba56ed1398ab1055f39fe852686ecad24a6306c80c490fa8e0165",
        "corpus": 5_183,
        "queries": 300,
        "license": "CC BY-NC 2.0 (SciFact upstream repository)",
        "license_url": "https://github.com/allenai/scifact/blob/master/LICENSE.md",
    },
    "nfcorpus": {
        "archive_url": "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/nfcorpus.zip",
        "md5": "a89dba18a62ef92f7d323ec890a0d38d",
        "sha256": "efe5be03f8c5b86a5870102d0599d227c8c6e2484328e68c6522560385671b0b",
        "corpus": 3_633,
        "queries": 323,
        "license": "Not specified by the BEIR archive; verify NFCorpus/NutritionFacts upstream terms before redistribution",
        "license_url": "https://github.com/beir-cellar/beir/wiki/Datasets-available",
    },
    "fiqa": {
        "archive_url": "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/fiqa.zip",
        "md5": "17918ed23cd04fb15047f73e6c3bd9d9",
        "sha256": "32c7df99ed21252fdfb2cf3f5673502a8d245ee0c44c4a133570d92ce2b3ad02",
        "corpus": 57_638,
        "queries": 648,
        "license": "FiQA states its train/test data are for non-commercial use only",
        "license_url": "https://sites.google.com/view/fiqa/home",
    },
}

MODELS = {
    "minilm": {
        "name": "sentence-transformers/all-MiniLM-L6-v2",
        "cache": MODEL_CACHE / "models--qdrant--all-MiniLM-L6-v2-onnx",
        "mps_cache": MODEL_CACHE / "mps" / "models--sentence-transformers--all-MiniLM-L6-v2",
        "query_prefix": "",
        "url": "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2",
        "license": "Apache-2.0",
        "dimensions": 384,
        "max_tokens": 256,
    },
    "bge": {
        "name": "BAAI/bge-small-en-v1.5",
        "cache": MODEL_CACHE / "models--qdrant--bge-small-en-v1.5-onnx-q",
        "mps_cache": MODEL_CACHE / "mps" / "models--BAAI--bge-small-en-v1.5",
        "query_prefix": QUERY_PREFIX_BGE,
        "url": "https://huggingface.co/BAAI/bge-small-en-v1.5",
        "license": "MIT",
        "dimensions": 384,
        "max_tokens": 512,
    },
}

_EMBEDDERS: dict[tuple[str, str], object] = {}


def get_embedder(model_key: str, backend: str):
    cache_key = (model_key, backend)
    if cache_key in _EMBEDDERS:
        return _EMBEDDERS[cache_key]
    spec = MODELS[model_key]
    if backend == "mps-fp32":
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(
            spec["name"], cache_folder=str(MODEL_CACHE / "mps"), device="mps"
        )
        model.max_seq_length = spec["max_tokens"]
    elif backend == "fastembed-int8-cpu":
        from fastembed import TextEmbedding

        model = TextEmbedding(
            model_name=spec["name"], cache_dir=str(MODEL_CACHE),
            threads=8, local_files_only=True,
        )
    else:
        raise ValueError(f"unsupported dense backend: {backend}")
    _EMBEDDERS[cache_key] = model
    return model


_PROVENANCE_RUN = None


def atomic_json(path: Path, value: object) -> None:
    if _PROVENANCE_RUN is not None:
        _PROVENANCE_RUN.write_json(path, value)
        return
    # Library callers may create ignored vector-cache metadata; their runner owns
    # result provenance. Direct CLI execution always installs the context below.
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    os.replace(temp, path)


def hash_file(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file() and ".lock" not in p.name):
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        with item.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def canonical_text(row: dict) -> str:
    """One canonical representation shared by BM25 and both dense models."""
    return "\n".join(part.strip() for part in (row.get("title", ""), row.get("text", "")) if part.strip())


def load_jsonl(path: Path) -> list[dict]:
    with path.open() as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_dataset(name: str) -> tuple[list[str], list[str], list[str], list[str], dict[str, dict[str, int]]]:
    folder = DATA_DIR / name / name
    corpus_rows = load_jsonl(folder / "corpus.jsonl")
    query_rows = load_jsonl(folder / "queries.jsonl")
    qrels: dict[str, dict[str, int]] = defaultdict(dict)
    with (folder / "qrels" / "test.tsv").open() as handle:
        next(handle)
        for line in handle:
            qid, did, score = line.rstrip("\n").split("\t")
            qrels[qid][did] = int(score)
    queries_by_id = {str(row["_id"]): row["text"] for row in query_rows}
    query_ids = sorted(qrels)
    missing = [qid for qid in query_ids if qid not in queries_by_id]
    if missing:
        raise ValueError(f"{name}: qrels reference missing query IDs: {missing[:5]}")
    doc_ids = [str(row["_id"]) for row in corpus_rows]
    texts = [canonical_text(row) for row in corpus_rows]
    query_texts = [queries_by_id[qid] for qid in query_ids]
    expected = DATASETS[name]
    if len(doc_ids) != expected["corpus"] or len(query_ids) != expected["queries"]:
        raise ValueError(f"{name}: expected {expected['corpus']}/{expected['queries']}, got {len(doc_ids)}/{len(query_ids)}")
    return doc_ids, texts, query_ids, query_texts, dict(qrels)


def stable_rows_hash(ids: list[str], texts: list[str]) -> str:
    digest = hashlib.sha256()
    for row_id, text in zip(ids, texts, strict=True):
        digest.update(row_id.encode())
        digest.update(b"\0")
        digest.update(text.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def normalize_rows(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    np.divide(matrix, np.maximum(norms, 1e-12), out=matrix)
    return matrix


def linear_metrics_for_query(ranked_ids: list[str], qrels: dict[str, int]) -> dict[str, float]:
    """BEIR/trec_eval nDCG uses the qrel itself as gain, not 2**rel-1."""
    relevant = {doc: float(score) for doc, score in qrels.items() if score > 0}
    ranked = list(dict.fromkeys(ranked_ids))
    gains = [relevant.get(doc, 0.0) for doc in ranked[:10]]
    dcg = sum(gain / np.log2(rank + 2) for rank, gain in enumerate(gains))
    ideal = sum(
        gain / np.log2(rank + 2)
        for rank, gain in enumerate(sorted(relevant.values(), reverse=True)[:10])
    )
    rr = next((1 / rank for rank, doc in enumerate(ranked[:10], 1) if doc in relevant), 0.0)
    return {
        "ndcg@10": float(dcg / ideal if ideal else 0.0),
        "recall@10": len(set(ranked[:10]) & relevant.keys()) / len(relevant) if relevant else 0.0,
        "mrr@10": rr,
    }


def aggregate_linear_metrics(run: dict[str, list[str]], qrels: dict[str, dict[str, int]]) -> dict:
    rows = [linear_metrics_for_query(run.get(qid, []), labels) for qid, labels in qrels.items()]
    names = ("ndcg@10", "recall@10", "mrr@10")
    return {
        **{name: sum(row[name] for row in rows) / len(rows) if rows else 0.0 for name in names},
        "query_count": len(rows),
    }


def validate_linear_metric() -> None:
    actual = linear_metrics_for_query(["rel1", "rel2"], {"rel1": 1, "rel2": 2})["ndcg@10"]
    expected = (1 + 2 / np.log2(3)) / (2 + 1 / np.log2(3))
    if not np.isclose(actual, expected, atol=1e-12):
        raise AssertionError(f"linear nDCG self-test failed: {actual} != {expected}")


def embed_to_cache(
    *, dataset: str, model_key: str, kind: str, ids: list[str], texts: list[str],
    prefix: str, rebuild: bool, backend: str,
) -> tuple[np.ndarray, float, dict]:
    model_spec = MODELS[model_key]
    embedder = get_embedder(model_key, backend)
    stem = f"{dataset}-{model_key}-{kind}"
    array_path = DATA_DIR / f"{stem}.npy"
    meta_path = DATA_DIR / f"{stem}.meta.json"
    partial_path = DATA_DIR / f"{stem}.partial.npy"
    partial_meta_path = DATA_DIR / f"{stem}.partial.meta.json"
    content_hash = stable_rows_hash(ids, texts)
    if backend == "mps-fp32":
        artifact_path = model_spec["mps_cache"]
        backend_packages = {
            name: importlib.metadata.version(name)
            for name in ("torch", "sentence-transformers", "transformers")
        }
        precision = "float32"
    else:
        artifact_path = model_spec["cache"]
        backend_packages = {
            name: importlib.metadata.version(name)
            for name in ("fastembed", "onnxruntime")
        }
        precision = "FastEmbed quantized ONNX model artifact"
    model_tree_sha256 = tree_hash(artifact_path)
    expected = {
        "dataset": dataset,
        "model": model_spec["name"],
        "kind": kind,
        "rows": len(texts),
        "dimensions": model_spec["dimensions"],
        "content_sha256": content_hash,
        "query_prefix": prefix,
        "normalized": True,
        "dtype": "float32",
        "backend": backend,
        "precision": precision,
        "model_cache_tree_sha256": model_tree_sha256,
        "backend_packages": backend_packages,
    }
    if not rebuild and array_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if all(meta.get(key) == value for key, value in expected.items()):
            matrix = np.load(array_path, mmap_mode="r")
            if (
                matrix.shape == (len(texts), model_spec["dimensions"])
                and meta.get("array_sha256") == hash_file(array_path)
            ):
                print(f"[{dataset}] reuse {model_key} {kind} vectors {matrix.shape}", flush=True)
                return matrix, 0.0, {**meta, "cache_reused": True, "elapsed_seconds_this_run": 0.0}

    start_index = 0
    previous_elapsed = 0.0
    if not rebuild and partial_path.exists() and partial_meta_path.exists():
        partial_meta = json.loads(partial_meta_path.read_text())
        if all(partial_meta.get(key) == value for key, value in expected.items()):
            start_index = int(partial_meta.get("completed_rows", 0))
            previous_elapsed = float(partial_meta.get("elapsed_seconds", 0.0))
            matrix = np.lib.format.open_memmap(partial_path, mode="r+")
            if matrix.shape != (len(texts), model_spec["dimensions"]) or not 0 <= start_index <= len(texts):
                start_index = 0
        else:
            start_index = 0
    if start_index == 0:
        partial_path.unlink(missing_ok=True)
        partial_meta_path.unlink(missing_ok=True)
        matrix = np.lib.format.open_memmap(
            partial_path, mode="w+", dtype=np.float32,
            shape=(len(texts), model_spec["dimensions"]),
        )
    print(
        f"[{dataset}] embed {len(texts)} {kind} rows with {model_key}; resume at {start_index}",
        flush=True,
    )
    started = time.perf_counter()
    remaining = texts[start_index:]
    inputs = [prefix + text for text in remaining] if prefix else remaining
    if backend == "mps-fp32":
        def vectors():
            for offset in range(0, len(inputs), 128):
                batch = embedder.encode(
                    inputs[offset:offset + 128], batch_size=32,
                    convert_to_numpy=True, normalize_embeddings=False,
                    show_progress_bar=False, device="mps",
                )
                yield from batch
        generator = vectors()
    else:
        # FastEmbed 0.8.0 query_embed delegates directly to embed and adds no
        # model-specific prefix, so the BGE instruction is applied once here.
        generator = (
            embedder.query_embed(inputs, batch_size=8)
            if kind == "queries" else embedder.embed(inputs, batch_size=8)
        )
    count = start_index
    checkpoint = start_index
    for count, vector in enumerate(generator, start=start_index + 1):
        matrix[count - 1] = vector
        if count - checkpoint >= 64:
            matrix.flush()
            cumulative = previous_elapsed + time.perf_counter() - started
            atomic_json(
                partial_meta_path,
                {**expected, "completed_rows": count, "elapsed_seconds": cumulative, "updated_at": now()},
            )
            checkpoint = count
            print(f"[{dataset}] {model_key} {kind} {count}/{len(texts)}", flush=True)
    if count != len(texts):
        raise RuntimeError(f"{model_key}/{kind}: embedded {count}, expected {len(texts)}")
    elapsed_this_run = time.perf_counter() - started
    elapsed = previous_elapsed + elapsed_this_run
    for offset in range(0, len(texts), 4096):
        matrix[offset : offset + 4096] = normalize_rows(np.asarray(matrix[offset : offset + 4096]))
    matrix.flush()
    del matrix
    os.replace(partial_path, array_path)
    partial_meta_path.unlink(missing_ok=True)
    meta = {**expected, "index_seconds": elapsed, "array_sha256": hash_file(array_path), "created_at": now()}
    atomic_json(meta_path, meta)
    return np.load(array_path, mmap_mode="r"), elapsed_this_run, {
        **meta, "cache_reused": False, "elapsed_seconds_this_run": elapsed_this_run,
    }


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def top_indices(scores: np.ndarray, doc_ids: list[str], limit: int) -> list[int]:
    count = min(limit, len(scores))
    candidates = np.argpartition(scores, -count)[-count:]
    threshold = float(np.min(scores[candidates]))
    above = np.flatnonzero(scores > threshold).tolist()
    tied = np.flatnonzero(scores == threshold).tolist()
    above.sort(key=lambda i: (-float(scores[i]), doc_ids[i]))
    tied.sort(key=lambda i: doc_ids[i])
    return (above + tied[: count - len(above)])[:count]


def dense_rankings(
    documents: np.ndarray, queries: np.ndarray, doc_ids: list[str], query_ids: list[str], limit: int
) -> tuple[dict[str, list[str]], list[float]]:
    run: dict[str, list[str]] = {}
    latencies: list[float] = []
    doc_index = {doc_id: index for index, doc_id in enumerate(doc_ids)}
    for index, (qid, vector) in enumerate(zip(query_ids, queries, strict=True), start=1):
        started = time.perf_counter()
        scores = documents @ vector
        if qid in doc_index:
            scores[doc_index[qid]] = -np.inf
        indices = top_indices(scores, doc_ids, limit)
        latencies.append(time.perf_counter() - started)
        run[qid] = [doc_ids[i] for i in indices]
        if index % 100 == 0:
            print(f"dense retrieval {index}/{len(query_ids)}", flush=True)
    return run, latencies


def bm25_rankings(texts: list[str], queries: list[str], doc_ids: list[str], query_ids: list[str], limit: int):
    started = time.perf_counter()
    tokenized = [tokenize(text) for text in texts]
    bm25 = BM25Okapi(tokenized)
    build_seconds = time.perf_counter() - started
    run: dict[str, list[str]] = {}
    latencies: list[float] = []
    doc_index = {doc_id: index for index, doc_id in enumerate(doc_ids)}
    for index, (qid, query) in enumerate(zip(query_ids, queries, strict=True), start=1):
        started = time.perf_counter()
        scores = bm25.get_scores(tokenize(query))
        if qid in doc_index:
            scores[doc_index[qid]] = -np.inf
        indices = top_indices(scores, doc_ids, limit)
        latencies.append(time.perf_counter() - started)
        run[qid] = [doc_ids[i] for i in indices]
        if index % 100 == 0:
            print(f"BM25 retrieval {index}/{len(query_ids)}", flush=True)
    return run, latencies, build_seconds


def fuse_runs(
    runs: list[dict[str, list[str]]], component_latencies: list[list[float]], query_ids: list[str], limit: int
) -> tuple[dict[str, list[str]], list[float], list[float]]:
    output: dict[str, list[str]] = {}
    total_latencies, fusion_latencies = [], []
    for index, qid in enumerate(query_ids):
        started = time.perf_counter()
        output[qid] = reciprocal_rank_fusion([run[qid] for run in runs], k=RRF_K, limit=limit)
        fusion = time.perf_counter() - started
        fusion_latencies.append(fusion)
        total_latencies.append(sum(values[index] for values in component_latencies) + fusion)
    return output, total_latencies, fusion_latencies


def evaluate(run: dict[str, list[str]], qrels: dict[str, dict[str, int]], latencies: list[float]) -> dict:
    return {
        "metrics": aggregate_linear_metrics(run, qrels),
        "latency": latency_summary(latencies),
        "rankings": run,
    }


def bootstrap(systems: dict[str, dict], qrels: dict[str, dict[str, int]]) -> dict:
    reference = "minilm_hybrid_rrf"
    query_ids = sorted(qrels)
    result = {}
    for system, value in systems.items():
        result[system] = {}
        for metric in ("ndcg@10", "recall@10", "mrr@10"):
            left = [linear_metrics_for_query(value["rankings"][qid], qrels[qid])[metric] for qid in query_ids]
            right = [linear_metrics_for_query(systems[reference]["rankings"][qid], qrels[qid])[metric] for qid in query_ids]
            result[system][metric] = paired_bootstrap_difference(
                left, right, samples=BOOTSTRAP_SAMPLES, seed=SEED
            )
    return {"reference": reference, "method": "paired query bootstrap", "comparisons": result}


def archive_metadata(name: str) -> dict:
    spec = DATASETS[name]
    archive = DATA_DIR / f"{name}.zip"
    actual_md5, actual_sha256 = hash_file(archive, "md5"), hash_file(archive)
    if actual_md5 != spec["md5"] or actual_sha256 != spec["sha256"]:
        raise ValueError(f"{name}: archive checksum mismatch")
    return {
        "url": spec["archive_url"],
        "bytes": archive.stat().st_size,
        "official_beir_md5": spec["md5"],
        "actual_md5": actual_md5,
        "actual_sha256": actual_sha256,
        "license_note": spec["license"],
        "license_url": spec["license_url"],
    }


def run_dataset(name: str, rebuild: bool, limit: int, backend: str) -> dict:
    print(f"[{name}] load full corpus", flush=True)
    doc_ids, texts, query_ids, queries, qrels = load_dataset(name)
    content_hash = stable_rows_hash(doc_ids, texts)
    query_hash = stable_rows_hash(query_ids, queries)
    qrel_pairs = sum(len(rows) for rows in qrels.values())

    bm25, bm25_latency, bm25_build = bm25_rankings(texts, queries, doc_ids, query_ids, limit)
    dense_runs, dense_latencies, vector_meta, vector_times = {}, {}, {}, {}
    for model_key in ("minilm", "bge"):
        doc_vectors, doc_seconds, doc_meta = embed_to_cache(
            dataset=name, model_key=model_key, kind="documents", ids=doc_ids, texts=texts,
            prefix="", rebuild=rebuild, backend=backend,
        )
        query_vectors, query_seconds, query_meta = embed_to_cache(
            dataset=name, model_key=model_key, kind="queries", ids=query_ids, texts=queries,
            prefix=MODELS[model_key]["query_prefix"], rebuild=rebuild, backend=backend,
        )
        dense_runs[model_key], dense_latencies[model_key] = dense_rankings(
            doc_vectors, query_vectors, doc_ids, query_ids, limit
        )
        vector_meta[model_key] = {"documents": doc_meta, "queries": query_meta}
        vector_times[model_key] = {
            "document_embedding_seconds": doc_meta.get("index_seconds", doc_seconds),
            "query_embedding_seconds": query_meta.get("index_seconds", query_seconds),
            "elapsed_seconds_this_run": doc_seconds + query_seconds,
        }

    minilm_hybrid, minilm_hybrid_latency, minilm_fusion = fuse_runs(
        [bm25, dense_runs["minilm"]], [bm25_latency, dense_latencies["minilm"]], query_ids, limit
    )
    bge_hybrid, bge_hybrid_latency, bge_fusion = fuse_runs(
        [bm25, dense_runs["bge"]], [bm25_latency, dense_latencies["bge"]], query_ids, limit
    )
    three_way, three_way_latency, three_way_fusion = fuse_runs(
        [bm25, dense_runs["minilm"], dense_runs["bge"]],
        [bm25_latency, dense_latencies["minilm"], dense_latencies["bge"]], query_ids, limit
    )
    systems = {
        "bm25": evaluate(bm25, qrels, bm25_latency),
        "minilm_dense": evaluate(dense_runs["minilm"], qrels, dense_latencies["minilm"]),
        "bge_dense": evaluate(dense_runs["bge"], qrels, dense_latencies["bge"]),
        "minilm_hybrid_rrf": evaluate(minilm_hybrid, qrels, minilm_hybrid_latency),
        "bge_hybrid_rrf": evaluate(bge_hybrid, qrels, bge_hybrid_latency),
        "three_way_rrf": evaluate(three_way, qrels, three_way_latency),
    }
    systems["minilm_hybrid_rrf"]["fusion_only_latency"] = latency_summary(minilm_fusion)
    systems["bge_hybrid_rrf"]["fusion_only_latency"] = latency_summary(bge_fusion)
    systems["three_way_rrf"]["fusion_only_latency"] = latency_summary(three_way_fusion)
    return {
        "corpus_count": len(doc_ids),
        "test_query_count": len(query_ids),
        "qrel_pairs": qrel_pairs,
        "canonical_content_sha256": content_hash,
        "test_queries_sha256": query_hash,
        "archive": archive_metadata(name),
        "index": {"bm25_build_seconds": bm25_build, "dense": vector_times},
        "vector_cache": vector_meta,
        "systems": systems,
        "paired_bootstrap_vs_minilm_hybrid": bootstrap(systems, qrels),
    }


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def package_versions(backend: str) -> dict[str, str]:
    names = ["rank-bm25", "numpy"]
    names += ["torch", "sentence-transformers", "transformers"] if backend == "mps-fp32" else ["fastembed", "onnxruntime"]
    return {name: importlib.metadata.version(name) for name in names}


def model_metadata(backend: str) -> dict:
    result = {}
    for key, spec in MODELS.items():
        artifact_path = spec["mps_cache"] if backend == "mps-fp32" else spec["cache"]
        onnx = None
        if backend != "mps-fp32":
            metadata = json.loads((spec["cache"] / "files_metadata.json").read_text())
            onnx = next((value for name, value in metadata.items() if name.endswith(".onnx")), None)
        result[key] = {
            "name": spec["name"], "url": spec["url"], "license": spec["license"],
            "dimensions": spec["dimensions"], "max_tokens": spec["max_tokens"],
            "query_prefix_exact": spec["query_prefix"], "passage_prefix": "",
            "runtime_backend": backend,
            "artifact_cache_tree_sha256": tree_hash(artifact_path),
            "fastembed_onnx_blob_metadata": onnx,
        }
    return result


def macro_summary(datasets: dict[str, dict]) -> dict:
    system_names = next(iter(datasets.values()))["systems"].keys()
    metrics = ("ndcg@10", "recall@10", "mrr@10")
    return {
        system: {
            metric: float(np.mean([dataset["systems"][system]["metrics"][metric] for dataset in datasets.values()]))
            for metric in metrics
        }
        for system in system_names
    }


def main() -> None:
    global _PROVENANCE_RUN
    validate_linear_metric()
    parser = argparse.ArgumentParser()
    parser.add_argument("--datasets", default="scifact,nfcorpus,fiqa")
    parser.add_argument("--top-k", type=int, default=RANKING_LIMIT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--backend", choices=("mps-fp32", "fastembed-int8-cpu"), default="mps-fp32")
    parser.add_argument("--rebuild", action="store_true", help="rebuild dense caches")
    add_provenance_argument(parser)
    args = parser.parse_args()
    benchmark_run = BenchmarkRun(allow_dirty=args.allow_dirty)
    _PROVENANCE_RUN = benchmark_run
    names = [name.strip() for name in args.datasets.split(",") if name.strip()]
    unknown = set(names) - DATASETS.keys()
    if unknown:
        raise SystemExit(f"unknown datasets: {sorted(unknown)}")
    if args.top_k < 10:
        raise SystemExit("--top-k must be >= 10")

    script_hash = hash_file(Path(__file__))
    phase_dir = DATA_DIR / "phases"
    phase_dir.mkdir(parents=True, exist_ok=True)
    datasets = {}
    for name in names:
        phase_path = phase_dir / f"{name}-results.json"
        if not args.rebuild and phase_path.exists():
            phase = json.loads(phase_path.read_text())
            if (
                phase.get("script_sha256") == script_hash
                and phase.get("top_k") == args.top_k
                and phase.get("backend") == args.backend
            ):
                print(f"[{name}] reuse complete result phase", flush=True)
                datasets[name] = phase["result"]
                continue
        result = run_dataset(name, args.rebuild, args.top_k, args.backend)
        atomic_json(
            phase_path,
            {"script_sha256": script_hash, "top_k": args.top_k, "backend": args.backend, "result": result},
        )
        datasets[name] = result
        print(f"[{name}] complete; phase saved", flush=True)

    output = {
        "schema_version": 1,
        "created_at": now(),
        "benchmark": "full-corpus BEIR cross-domain retrieval",
        "script_sha256": script_hash,
        "command": ".bench-mps-venv/bin/python benchmarks/cross_domain.py --datasets scifact,nfcorpus,fiqa --top-k 100 --backend mps-fp32",
        "runtime": {
            "python": sys.version, "platform": platform.platform(), "dense_backend": args.backend,
            "device": "Apple Metal Performance Shaders" if args.backend == "mps-fp32" else "CPU",
            "packages": package_versions(args.backend), "paid_api_calls": 0,
        },
        "protocol": {
            "ranking_limit": args.top_k,
            "metrics_cutoff": 10,
            "ndcg_gain": "linear qrel gain, matching trec_eval/BEIR ndcg_cut (not exponential gain)",
            "rrf_k": RRF_K,
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "bootstrap_seed": SEED,
            "canonical_document_text": "non-empty title, newline, text; identical input text for every retriever",
            "bm25_tokenization": "Unicode regex word tokens lowercased; no stemming or stopword removal",
            "dense_similarity": "L2-normalized vectors, exact exhaustive dot product",
            "dense_latency_scope": "warm exact ranking over cached document and query vectors; query embedding excluded and reported under index",
            "hybrid_latency_scope": "sum of measured component ranking latency plus measured RRF fusion; fusion-only also reported",
            "dense_truncation": "Full canonical input supplied; MiniLM truncates at256tokens and BGE at512. MPS uses explicit SentenceTransformer max_seq_length; CPU uses FastEmbed tokenizer configuration.",
            "qrels_isolation": "Test qrels select test query IDs. Relevance values are used only for evaluation after rankings; no qrel-based tuning.",
            "query_document_same_id": "excluded from ranking to match BEIR retrieval evaluation; FiQA has 55 test-query/document ID collisions and none is a relevant self-pair",
            "bge_query_instruction": QUERY_PREFIX_BGE,
            "bge_passage_instruction": "none",
            "training_overlap_limitation": "Pretraining/fine-tuning overlap with BEIR evaluation documents or queries was not independently audited; scores may reflect overlap.",
            "hardware_timing_limitation": "One local run using the recorded backend (MPS FP32 embeddings for this run; CPU exact ranking). Shared-machine index and latency measurements are not directly comparable with production Store timings.",
        },
        "sources": {
            "beir_repository": "https://github.com/beir-cellar/beir",
            "beir_dataset_registry": "https://github.com/beir-cellar/beir/wiki/Datasets-available",
            "bge_model_card": MODELS["bge"]["url"],
            "minilm_model_card": MODELS["minilm"]["url"],
        },
        "models": model_metadata(args.backend),
        "datasets": datasets,
        "macro_average_equal_weight_per_dataset": macro_summary(datasets),
    }
    atomic_json(args.output, output)
    print(f"wrote {args.output}", flush=True)


if __name__ == "__main__":
    main()
