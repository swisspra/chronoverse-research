#!/usr/bin/env python3
"""Independent read-only verifier for cross-domain v3 JSON or JSON.gz."""
from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULT = ROOT / "docs" / "benchmarks-v3" / "cross-domain-results.json"
DATA_ROOT = ROOT / ".benchmark-data" / "v2"
DATASETS = {"scifact": (5_183, 300), "nfcorpus": (3_633, 323), "fiqa": (57_638, 648)}
SYSTEMS = {
    "strong_bm25",
    "minilm_dense",
    "bge_dense",
    "minilm_hybrid_rrf",
    "bge_hybrid_rrf",
    "three_way_rrf",
}
METRICS = ("ndcg@10", "recall@10", "mrr@10")
TOLERANCE = 1e-12


def read_result(path: Path) -> dict:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text())


def load_qrels(name: str) -> dict[str, dict[str, int]]:
    path = DATA_ROOT / name / name / "qrels" / "test.tsv"
    output: dict[str, dict[str, int]] = {}
    with path.open(encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            qid, docid, grade = line.rstrip("\n").split("\t")
            output.setdefault(qid, {})[docid] = int(grade)
    return output


def query_metrics(ranking: list[str], labels: dict[str, int]) -> dict[str, float]:
    relevant = {docid: float(grade) for docid, grade in labels.items() if grade > 0}
    unique = list(dict.fromkeys(ranking))
    gains = [relevant.get(docid, 0.0) for docid in unique[:10]]
    dcg = sum(gain / math.log2(rank + 2) for rank, gain in enumerate(gains))
    ideal = sum(
        gain / math.log2(rank + 2)
        for rank, gain in enumerate(sorted(relevant.values(), reverse=True)[:10])
    )
    return {
        "ndcg@10": dcg / ideal if ideal else 0.0,
        "recall@10": len(set(unique[:10]) & set(relevant)) / len(relevant) if relevant else 0.0,
        "mrr@10": next((1 / rank for rank, docid in enumerate(unique[:10], 1) if docid in relevant), 0.0),
    }


def aggregate(rankings: dict[str, list[str]], qrels: dict[str, dict[str, int]]) -> tuple[dict, dict]:
    per_query = {qid: query_metrics(rankings.get(qid, []), labels) for qid, labels in qrels.items()}
    return (
        {metric: sum(row[metric] for row in per_query.values()) / len(per_query) for metric in METRICS},
        per_query,
    )


def verify_system(system: dict, qrels: dict[str, dict[str, int]], label: str) -> dict[str, dict[str, float]]:
    rankings = system["rankings"]
    assert set(rankings) == set(qrels), f"{label}: query IDs differ from official TEST qrels"
    for qid, docs in rankings.items():
        assert len(docs) <= 100, f"{label}/{qid}: ranking exceeds top 100"
        assert len(docs) == len(set(docs)), f"{label}/{qid}: duplicate result"
        assert qid not in docs, f"{label}/{qid}: self document was not excluded"
    metrics, per_query = aggregate(rankings, qrels)
    for metric, actual in metrics.items():
        recorded = float(system["metrics"][metric])
        assert math.isclose(actual, recorded, abs_tol=TOLERANCE), (
            f"{label}: {metric} recorded {recorded} != independent {actual}"
        )
    assert system["metrics"]["query_count"] == len(qrels), f"{label}: wrong query count"
    return per_query


def verify_interval(row: dict, label: str) -> None:
    raw = row["raw_ci95"]
    simultaneous = row["simultaneous_ci"]
    assert len(raw) == len(simultaneous) == 2, f"{label}: malformed interval"
    assert -1 <= simultaneous[0] <= raw[0] <= raw[1] <= simultaneous[1] <= 1, (
        f"{label}: simultaneous interval must contain pointwise interval"
    )
    assert 0 <= row["p_value"] <= row["holm_p_value"] <= 1, f"{label}: invalid p values"
    assert row["simultaneous_ci"] != row["raw_ci95"] or row["mean_difference"] == 0, (
        f"{label}: simultaneous and pointwise intervals are unexpectedly identical"
    )


def assert_mean(row: dict, left: list[float], right: list[float], label: str) -> None:
    expected = sum(a - b for a, b in zip(left, right, strict=True)) / len(left)
    assert math.isclose(expected, row["mean_difference"], abs_tol=TOLERANCE), (
        f"{label}: recorded mean difference does not match rankings"
    )
    verify_interval(row, label)


def verify(path: Path) -> dict:
    result = read_result(path)
    assert result["protocol"]["ndcg_gain"].startswith("linear"), "gain convention not declared linear"
    assert result["protocol"]["rrf_k"] == 60 and result["protocol"]["rrf_candidate_pool"] == 100
    per_query: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    qrels_by_dataset = {}
    for name, (corpus_count, query_count) in DATASETS.items():
        dataset = result["datasets"][name]
        qrels = load_qrels(name)
        qrels_by_dataset[name] = qrels
        assert dataset["corpus_count"] == corpus_count
        assert dataset["test_query_count"] == query_count == len(qrels)
        assert dataset["strong_lexical"]["indexed_document_count"] + dataset["strong_lexical"]["empty_document_count"] == corpus_count
        per_query[name] = {}
        for context in ("256", "512"):
            systems = dataset["matched_contexts"][context]["systems"]
            assert set(systems) == SYSTEMS, f"{name}@{context}: six-system set changed"
            per_query[name][context] = {
                system: verify_system(value, qrels, f"{name}@{context}/{system}")
                for system, value in systems.items()
            }
        weak = dataset["weak_lexical_supplement"]["systems"]
        for system in ("bm25", "bge_dense", "bge_hybrid_rrf"):
            verify_system(weak[system], qrels, f"{name}/historical/{system}")

    families = result["inferential_families"]
    for context in ("256", "512"):
        family = families["primary_matched_context_families"][context]
        assert family["hypotheses"] == 15 == len(family["comparisons"])
        for name in DATASETS:
            reference = per_query[name][context]["minilm_hybrid_rrf"]
            qids = sorted(qrels_by_dataset[name])
            for system in SYSTEMS - {"minilm_hybrid_rrf"}:
                key = f"{name}/{system}-minus-minilm_hybrid_rrf"
                assert_mean(
                    family["comparisons"][key],
                    [per_query[name][context][system][qid]["ndcg@10"] for qid in qids],
                    [reference[qid]["ndcg@10"] for qid in qids],
                    key,
                )

    length = families["length_ablation_family"]
    assert length["hypotheses"] == 6 == len(length["comparisons"])
    for name in DATASETS:
        qids = sorted(qrels_by_dataset[name])
        for system in ("minilm_dense", "bge_dense"):
            key = f"{name}/{system}@512-minus-@256"
            assert_mean(
                length["comparisons"][key],
                [per_query[name]["512"][system][qid]["ndcg@10"] for qid in qids],
                [per_query[name]["256"][system][qid]["ndcg@10"] for qid in qids],
                key,
            )

    fiqa = families["fiqa_hybrid_minus_bge_confirmatory_family"]
    assert fiqa["hypotheses"] == 3 == len(fiqa["comparisons"])
    qids = sorted(qrels_by_dataset["fiqa"])
    for context in ("256", "512"):
        key = f"strong_bm25@{context}/bge_hybrid-minus-bge_dense"
        assert_mean(
            fiqa["comparisons"][key],
            [per_query["fiqa"][context]["bge_hybrid_rrf"][qid]["ndcg@10"] for qid in qids],
            [per_query["fiqa"][context]["bge_dense"][qid]["ndcg@10"] for qid in qids],
            key,
        )
    weak = result["datasets"]["fiqa"]["weak_lexical_supplement"]["systems"]
    weak_per_query = {
        system: aggregate(weak[system]["rankings"], qrels_by_dataset["fiqa"])[1]
        for system in ("bge_hybrid_rrf", "bge_dense")
    }
    key = "historical_weak_bm25/bge_hybrid-minus-bge_dense"
    assert_mean(
        fiqa["comparisons"][key],
        [weak_per_query["bge_hybrid_rrf"][qid]["ndcg@10"] for qid in qids],
        [weak_per_query["bge_dense"][qid]["ndcg@10"] for qid in qids],
        key,
    )
    return {
        "verified": True,
        "path": path.name,
        "datasets": len(DATASETS),
        "queries": sum(count for _, count in DATASETS.values()),
        "system_cells": len(DATASETS) * 2 * len(SYSTEMS),
        "independent_metric_aggregates": len(DATASETS) * 2 * len(SYSTEMS) * len(METRICS),
        "inferential_contrasts": 15 + 15 + 6 + 3,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_RESULT)
    args = parser.parse_args()
    print(json.dumps(verify(args.path), indent=2))


if __name__ == "__main__":
    main()
