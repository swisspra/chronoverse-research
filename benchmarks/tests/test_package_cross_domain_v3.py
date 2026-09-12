import gzip
import json

from benchmarks.package_cross_domain_v3 import compact_dataset, sha256_bytes


def test_compact_dataset_removes_rankings_but_keeps_metrics_and_vectors():
    system = {"metrics": {"ndcg@10": 1}, "latency": {"samples": 1}, "rankings": {"q": ["d"]}}
    dataset = {
        "corpus_count": 1,
        "test_query_count": 1,
        "qrel_pairs": 1,
        "canonical_content_sha256": "a",
        "test_queries_sha256": "b",
        "strong_lexical": {},
        "official_pyserini_multifield_sanity": {},
        "truncation": {},
        "matched_contexts": {"256": {"systems": {"s": system}, "vector_cache": {"m": {}}}},
        "weak_lexical_supplement": {
            "label": "weak",
            "source": "source.json",
            "source_sha256": "c",
            "systems": {"bm25": system},
        },
    }
    compact = compact_dataset(dataset)
    assert compact["matched_contexts"]["256"]["systems"]["s"]["metrics"]["ndcg@10"] == 1
    assert "rankings" not in compact["matched_contexts"]["256"]["systems"]["s"]
    assert compact["matched_contexts"]["256"]["vector_cache"] == {"m": {}}
    assert "rankings" not in compact["weak_lexical_supplement"]["systems"]["bm25"]


def test_deterministic_gzip_roundtrip_and_hash():
    raw = json.dumps({"value": 1}, sort_keys=True).encode()
    left = gzip.compress(raw, compresslevel=9, mtime=0)
    right = gzip.compress(raw, compresslevel=9, mtime=0)
    assert left == right
    assert gzip.decompress(left) == raw
    assert sha256_bytes(raw) == sha256_bytes(gzip.decompress(left))
