import json

import numpy as np
import pytest

from benchmarks import cross_domain_v3 as v3


class FakeTokenizer:
    def __call__(self, values, **kwargs):
        assert kwargs["add_special_tokens"] is True
        assert kwargs["truncation"] is False
        return {"length": [len(value.split()) + 2 for value in values]}


def test_token_lengths_are_measured_before_truncation_and_include_prefix():
    lengths = v3.token_lengths(FakeTokenizer(), ["a b", "c"], prefix="p ")
    assert lengths == [5, 4]


def test_truncation_summary_reports_both_fixed_thresholds():
    row = v3.summarize_lengths([2, 256, 257, 512, 513])
    assert row["over_256"] == 3
    assert row["over_256_fraction"] == pytest.approx(0.6)
    assert row["over_512"] == 1
    assert row["over_512_fraction"] == pytest.approx(0.2)


def test_linear_ndcg_uses_qrel_grade_as_gain():
    actual = v3.linear_metrics_for_query(["rel1", "rel2"], {"rel1": 1, "rel2": 2})["ndcg@10"]
    expected = (1 + 2 / np.log2(3)) / (2 + 1 / np.log2(3))
    assert actual == pytest.approx(expected)


def test_top_indices_are_stable_across_ties():
    scores = np.asarray([0.5, 0.5, 0.5, 0.7], dtype=np.float32)
    ids = ["z", "a", "m", "x"]
    assert v3.top_indices(scores, ids, 3) == [3, 1, 2]


def test_reuse_v2_rejects_wrong_context_without_reading_cache():
    assert v3.reuse_v2_vectors("scifact", "minilm", "documents", [], [], 512) is None
    assert v3.reuse_v2_vectors("scifact", "bge", "documents", [], [], 256) is None


def test_frozen_v2_source_hash_matches_reuse_contract():
    assert v3.sha256(v3.V2_EXECUTED_SOURCE) == v3.V2_EXECUTED_SOURCE_SHA256


def test_embedding_cache_accepts_reviewed_source_and_rejects_unknown(monkeypatch):
    legacy = next(iter(v3.APPROVED_LEGACY_EMBEDDING_SOURCES))
    accepted = v3.validate_embedding_code({"embedding_source_sha256": legacy})
    assert accepted["method"] == "reviewed_legacy_whole_source_sha256"
    with pytest.raises(ValueError, match="unapproved"):
        v3.validate_embedding_code({"embedding_source_sha256": "0" * 64})


def test_embedding_fingerprint_accepts_only_current_code():
    current = v3.embedding_code_fingerprint()
    assert v3.validate_embedding_code({"embedding_code_fingerprint": current})["accepted"] == current
    with pytest.raises(ValueError, match="not current"):
        v3.validate_embedding_code({"embedding_code_fingerprint": "f" * 64})


def test_evaluate_retains_per_query_rankings():
    result = v3.evaluate({"q": ["d"]}, {"q": {"d": 1}}, [0.01])
    assert result["metrics"]["ndcg@10"] == 1
    assert result["rankings"] == {"q": ["d"]}
    assert result["latency"]["samples"] == 1
