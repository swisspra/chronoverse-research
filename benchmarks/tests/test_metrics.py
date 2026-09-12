import math
import pytest
from benchmarks.metrics import metrics_for_query, aggregate_metrics, reciprocal_rank_fusion, latency_summary


def test_rank_metrics_use_all_relevant_documents_and_cutoffs():
    actual=metrics_for_query(["miss","a","b"],{"a":1,"b":1,"c":1})
    assert actual["recall@5"] == pytest.approx(2/3)
    assert actual["recall@10"] == pytest.approx(2/3)
    assert actual["mrr@10"] == 0.5
    assert actual["hit@1"] == 0
    ideal=1+1/math.log2(3)+1/math.log2(4)
    assert actual["ndcg@10"] == pytest.approx((1/math.log2(3)+1/math.log2(4))/ideal)


def test_metrics_do_not_count_duplicate_hits_twice_or_omit_missing_queries():
    actual=metrics_for_query(["a","a"],{"a":1,"b":1})
    assert actual["recall@5"] == 0.5
    summary=aggregate_metrics({"q1":["a"]},{"q1":{"a":1},"q2":{"b":1}})
    assert summary["hit@1"] == 0.5
    assert summary["query_count"] == 2


def test_rrf_uses_rank_not_score_and_deterministic_ties():
    assert reciprocal_rank_fusion([["a","b"],["b","c"]],k=60) == ["b","a","c"]
    assert reciprocal_rank_fusion([["b"],["a"]],k=60) == ["a","b"]


def test_latency_percentiles_report_seconds():
    actual=latency_summary([1,2,3,4,5])
    assert actual["p50_seconds"] == 3
    assert actual["p95_seconds"] == pytest.approx(4.8)


def test_paired_bootstrap_constant_difference_is_exact():
    from benchmarks.metrics import paired_bootstrap_difference
    result=paired_bootstrap_difference([.8,.9,.7],[.6,.7,.5],samples=1000,seed=7)
    assert result['mean_difference'] == pytest.approx(.2)
    assert result['ci95_low'] == pytest.approx(.2)
    assert result['ci95_high'] == pytest.approx(.2)
