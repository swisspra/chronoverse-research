#!/usr/bin/env python3
"""Actual offline LightRAG retrieval benchmark over a pre-extracted synthetic KG.

This deliberately measures retrieval only. It does not exercise LightRAG's LLM
extraction or answer generation, and it is not a proxy for Microsoft GraphRAG.
"""

from __future__ import annotations
from benchmarks.provenance import BenchmarkRun, add_provenance_argument
import argparse

import argparse
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import math
import platform
import statistics
import sys
import tempfile
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
from fastembed import TextEmbedding
from lightrag import LightRAG, QueryParam
from lightrag.utils import EmbeddingFunc


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "benchmarks/data/temporal-v1.json"
DEFAULT_OUTPUT = ROOT / "docs/benchmarks/lightrag-results.json"
DEFAULT_CACHE = ROOT / ".model-cache"
MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def canonical_text(assertion: dict[str, Any]) -> str:
    """Mirror Chronoverse Store._text without importing the app environment."""
    parts = [
        assertion["subject"],
        assertion["predicate"],
        assertion["object"],
        assertion.get("summary", ""),
        *(item.get("text", "") for item in assertion.get("evidence", [])),
    ]
    return " ".join(str(part) for part in parts if part)


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def reciprocal_rank(ranking: list[str], gold: set[str]) -> float:
    for index, assertion_id in enumerate(ranking, 1):
        if assertion_id in gold:
            return 1.0 / index
    return 0.0


def make_custom_kg(assertions: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, str]]:
    chunks: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    content_to_id: dict[str, str] = {}
    ordinary_entities: dict[str, dict[str, Any]] = {}

    for assertion in assertions:
        assertion_id = assertion["id"]
        content = canonical_text(assertion)
        if content in content_to_id:
            raise ValueError(f"Canonical chunk collision cannot preserve IDs: {assertion_id}")
        content_to_id[content] = assertion_id
        file_path = f"assertion-{assertion_id}.txt"
        chunks.append({"content": content, "source_id": assertion_id, "file_path": file_path})

        hub = f"ASSERTION::{assertion_id}"
        metadata = (
            f"{content}\nworld={assertion['world']} plane={assertion['plane']} "
            f"perspective={assertion['perspective']} valid_from={assertion['valid_from']} "
            f"valid_to={assertion.get('valid_to') or 'open'} recorded_at={assertion['recorded_at']}"
        )
        entities.append({
            "entity_name": hub,
            "entity_type": "ASSERTION",
            "description": metadata,
            "source_id": assertion_id,
            "file_path": file_path,
        })

        subject_node = f"SUBJECT::{assertion['subject']}"
        object_node = f"OBJECT::{assertion['object']}"
        for node_name, name, kind in ((subject_node, assertion["subject"], "SUBJECT"), (object_node, assertion["object"], "OBJECT")):
            ordinary_entities.setdefault(node_name, {
                "entity_name": node_name,
                "entity_type": kind,
                "description": name,
                "source_id": assertion_id,
                "file_path": file_path,
            })

        relation = f"{assertion['subject']} {assertion['predicate']} {assertion['object']}"
        common = {
            "description": relation,
            "keywords": assertion["predicate"],
            "source_id": assertion_id,
            "weight": 1.0,
            "file_path": file_path,
        }
        # A unique assertion hub prevents LightRAG's undirected same-pair
        # relationship upsert from discarding provenance for changing facts.
        relationships.extend([
            {"src_id": subject_node, "tgt_id": hub, **common},
            {"src_id": hub, "tgt_id": object_node, **common},
        ])

    entities.extend(ordinary_entities.values())
    return {"chunks": chunks, "entities": entities, "relationships": relationships}, content_to_id


def extract_ranking(response: dict[str, Any], content_to_id: dict[str, str]) -> tuple[list[str], list[str]]:
    chunk_ids: list[str] = []
    assertion_ids: list[str] = []
    for chunk in response.get("data", {}).get("chunks", []):
        chunk_id = chunk.get("chunk_id", "")
        if chunk_id:
            chunk_ids.append(chunk_id)
        assertion_id = content_to_id.get(chunk.get("content", ""))
        if assertion_id and assertion_id not in assertion_ids:
            assertion_ids.append(assertion_id)
    return assertion_ids, chunk_ids


async def run(args: argparse.Namespace) -> dict[str, Any]:
    logging.getLogger().setLevel(logging.WARNING)
    for logger_name in ("lightrag", "nano-vectordb"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    fixture = json.loads(args.fixture.read_text())
    assertions = fixture["assertions"]
    queries = fixture["queries"]
    if not fixture.get("synthetic"):
        raise ValueError("This benchmark is restricted to an explicitly synthetic fixture")
    if any(not query.get("hl_keywords") or not query.get("ll_keywords") for query in queries):
        raise ValueError("Every query must supply non-empty hl_keywords and ll_keywords; no LLM keyword fallback is allowed")

    custom_kg, content_to_id = make_custom_kg(assertions)
    llm_calls: list[dict[str, Any]] = []

    async def no_llm(*call_args: Any, **call_kwargs: Any) -> str:
        llm_calls.append({"args": len(call_args), "kwargs": sorted(call_kwargs)})
        raise AssertionError("Unexpected LLM call in retrieval-only benchmark")

    model_started = time.perf_counter()
    model = TextEmbedding(MODEL, cache_dir=str(args.model_cache), threads=2, local_files_only=True)
    # Force model/session initialization into the separately reported setup time.
    probe = next(iter(model.embed(["Chronoverse offline benchmark"])))
    if probe.shape != (384,):
        raise ValueError(f"Unexpected embedding shape: {probe.shape}")
    model_setup_seconds = time.perf_counter() - model_started

    async def embed(texts: list[str]) -> np.ndarray:
        return np.asarray(list(model.embed(texts)), dtype=np.float32)

    work_temp = tempfile.TemporaryDirectory(prefix="lightrag-", dir=args.work_root)
    work_dir = Path(work_temp.name)
    rag = LightRAG(
        working_dir=str(work_dir),
        embedding_func=EmbeddingFunc(
            embedding_dim=384,
            func=embed,
            max_token_size=512,
            model_name=MODEL,
        ),
        llm_model_func=no_llm,
    )

    build_started = time.perf_counter()
    await rag.initialize_storages()
    await rag.ainsert_custom_kg(custom_kg)
    build_seconds = time.perf_counter() - build_started

    def parameters(query: dict[str, Any]) -> QueryParam:
        return QueryParam(
            mode="hybrid",
            hl_keywords=list(query["hl_keywords"]),
            ll_keywords=list(query["ll_keywords"]),
            top_k=args.top_k,
            chunk_top_k=args.top_k,
            enable_rerank=False,
        )

    # One unmeasured query warms embedding and storage read paths.
    await rag.aquery_data(queries[0]["query"], parameters(queries[0]))

    records: dict[str, dict[str, Any]] = {}
    all_latencies: list[float] = []
    for repetition in range(args.repetitions):
        for query in queries:
            started = time.perf_counter()
            response = await rag.aquery_data(query["query"], parameters(query))
            elapsed_ms = (time.perf_counter() - started) * 1000
            if response.get("status") != "success":
                raise RuntimeError(f"LightRAG query {query['id']} failed: {response}")
            ranking, chunk_ids = extract_ranking(response, content_to_id)
            all_latencies.append(elapsed_ms)
            record = records.setdefault(query["id"], {
                "id": query["id"],
                "category": query["category"],
                "query": query["query"],
                "hl_keywords": query["hl_keywords"],
                "ll_keywords": query["ll_keywords"],
                "scope": query["scope"],
                "gold_assertion_ids": query["gold_assertion_ids"],
                "retrieved_assertion_ids": ranking,
                "retrieved_chunk_ids": chunk_ids,
                "latency_samples_ms": [],
            })
            if ranking != record["retrieved_assertion_ids"] or chunk_ids != record["retrieved_chunk_ids"]:
                record["ranking_stable_across_repetitions"] = False
            record["latency_samples_ms"].append(round(elapsed_ms, 3))

    per_query = []
    for query in queries:
        record = records[query["id"]]
        samples = record.pop("latency_samples_ms")
        record.setdefault("ranking_stable_across_repetitions", True)
        record["latency_median_ms"] = round(statistics.median(samples), 3)
        record["latency_p95_ms"] = round(percentile(samples, 0.95), 3)
        record["latency_samples_ms"] = samples
        gold = set(record["gold_assertion_ids"])
        found = set(record["retrieved_assertion_ids"])
        record["recall_at_k"] = round(len(gold & found) / len(gold), 6) if gold else None
        record["precision_at_k"] = round(len(gold & found) / len(found), 6) if found else 0.0
        record["reciprocal_rank"] = round(reciprocal_rank(record["retrieved_assertion_ids"], gold), 6)
        per_query.append(record)

    await rag.finalize_storages()
    work_temp.cleanup()
    if llm_calls:
        raise AssertionError(f"LLM trap was invoked {len(llm_calls)} times")

    reciprocal_ranks = [item["reciprocal_rank"] for item in per_query]
    answerable_recalls = [item["recall_at_k"] for item in per_query if item["gold_assertion_ids"]]
    answerable_rrs = [item["reciprocal_rank"] for item in per_query if item["gold_assertion_ids"]]
    run_rankings = {item["id"]: item["retrieved_assertion_ids"] for item in per_query}
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from benchmarks.temporal import summarize_run
    temporal_capability = summarize_run(run_rankings, fixture, [value / 1000 for value in all_latencies])
    return {
        "schema_version": 1,
        "runner_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "track": "pre-extracted-KG retrieval-only",
        "fixture": {
            "path": str(args.fixture.relative_to(ROOT)),
            "sha256": sha256(args.fixture.read_bytes()).hexdigest(),
            "name": fixture.get("name"),
            "synthetic": fixture.get("synthetic"),
            "seed": fixture.get("seed"),
            "assertions": len(assertions),
            "events_not_ingested_as_temporal_policy": len(fixture.get("events", [])),
            "queries": len(queries),
            "disclaimer": fixture.get("disclaimer"),
        },
        "implementation": {
            "package": "lightrag-hku",
            "version": version("lightrag-hku"),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "api": ["LightRAG.ainsert_custom_kg", "LightRAG.aquery_data"],
            "query_mode": "hybrid",
            "top_k": args.top_k,
            "repetitions": args.repetitions,
            "reranker_enabled": False,
            "embedding": MODEL,
            "embedding_dimensions": 384,
            "embedding_runtime": "fastembed ONNX, local_files_only=True, threads=2",
            "default_storages": "LightRAG 1.5.7 local JSON KV + NanoVectorDB + NetworkX GraphML",
            "numeric_retrieval_scores_available": False,
            "llm_calls": 0,
            "answer_generation": False,
        },
        "representation": {
            "chunk": "Exact Chronoverse canonical joined assertion text; source alias is assertion ID",
            "graph": "Unique ASSERTION::<id> hub with SUBJECT::<label>→assertion and assertion→OBJECT::<label> relationships; prefixes preserve numeric/empty-looking labels through LightRAG entity normalization",
            "provenance": "The unique hub avoids LightRAG undirected same-entity-pair relationship replacement; returned hashed chunk IDs are mapped back to exact fixture assertion IDs by canonical content.",
        },
        "timing": {
            "comparability_note": 'Fresh keyword/query embeddings are encoded per request. The separate small temporal comparator run warms all query embeddings, so its latency is not directly comparable.',
            "model_setup_seconds": round(model_setup_seconds, 6),
            "kg_build_seconds": round(build_seconds, 6),
            "warm_query_samples": len(all_latencies),
            "warm_latency_p50_ms": round(percentile(all_latencies, 0.50), 3),
            "warm_latency_p95_ms": round(percentile(all_latencies, 0.95), 3),
        },
        "summary": {
            "answerable_queries": len(answerable_recalls),
            "empty_gold_queries": len(per_query) - len(answerable_recalls),
            "mean_recall_at_k_answerable": round(statistics.mean(answerable_recalls), 6),
            "mean_reciprocal_rank_answerable": round(statistics.mean(answerable_rrs), 6),
            "mean_reciprocal_rank_all": round(statistics.mean(reciprocal_ranks), 6),
            "temporal_capability_at_10": temporal_capability,
        },
        "limitations": [
            "This is actual LightRAG retrieval over a caller-supplied KG, not end-to-end document extraction.",
            "No answer generation or answer-quality comparison was run.",
            "LightRAG receives no native valid_at/known_at/world/plane/perspective filter; temporal events are not applied. Scope violations are therefore expected and must be measured from the unfiltered IDs.",
            "Supplied keyword lists bypass LightRAG's LLM keyword extraction. The no-LLM trap makes any unexpected model call fail the run.",
            "LightRAG aquery_data returns ranked records and chunk IDs but no comparable numeric retrieval score in this path.",
            "This is not Microsoft GraphRAG and must not be described as its proxy.",
        ],
        "other_systems": {
            "microsoft_graphrag": {
                "status": "excluded from this offline bounded run",
                "reason": "Its documented local/global query stack expects completed Parquet indexes, embeddings, community artifacts, and completion-model query configuration; BYOG local search still requires text units and embeddings.",
            },
            "graphiti": {
                "status": "excluded from this offline bounded run",
                "reason": "The official quickstart requires a graph DB plus LLM, embedding, and reranking providers for real ingest/search. Local providers are supported, but no suitable local LLM/graph service was provisioned for this no-API benchmark.",
            },
        },
        "sources": [
            {"title": "LightRAG official repository", "url": "https://github.com/HKUDS/LightRAG"},
            {"title": "LightRAG PyPI", "url": "https://pypi.org/project/lightrag-hku/"},
            {"title": "Microsoft GraphRAG overview", "url": "https://microsoft.github.io/graphrag/"},
            {"title": "Microsoft GraphRAG bring-your-own-graph", "url": "https://microsoft.github.io/graphrag/index/byog/"},
            {"title": "Graphiti official quickstart", "url": "https://github.com/getzep/graphiti/blob/main/examples/quickstart/README.md"},
        ],
        "queries": per_query,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model-cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--work-root", type=Path, default=ROOT / "benchmarks")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--repetitions", type=int, default=3)
    add_provenance_argument(parser)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    benchmark_run = BenchmarkRun(allow_dirty=args.allow_dirty)
    args.fixture = args.fixture.resolve()
    args.model_cache = args.model_cache.resolve()
    args.work_root.mkdir(parents=True, exist_ok=True)
    result = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    benchmark_run.write_json(args.output, result)
    print(json.dumps({
        "output": str(args.output),
        "build_seconds": result["timing"]["kg_build_seconds"],
        "warm_p50_ms": result["timing"]["warm_latency_p50_ms"],
        "warm_p95_ms": result["timing"]["warm_latency_p95_ms"],
        "mean_recall_at_k_answerable": result["summary"]["mean_recall_at_k_answerable"],
        "llm_calls": result["implementation"]["llm_calls"],
    }, indent=2))


if __name__ == "__main__":
    main()
