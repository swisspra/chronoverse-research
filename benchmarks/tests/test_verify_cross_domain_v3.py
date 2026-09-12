import pytest

from benchmarks.verify_cross_domain_v3 import aggregate, verify_system


def test_independent_linear_metric_handles_graded_qrels():
    metrics, _ = aggregate({"q": ["rel1", "rel2"]}, {"q": {"rel1": 1, "rel2": 2}})
    assert 0 < metrics["ndcg@10"] < 1


def test_metric_corruption_is_rejected():
    qrels = {"q": {"d": 1}}
    system = {
        "rankings": {"q": ["d"]},
        "metrics": {"ndcg@10": 0.99, "recall@10": 1.0, "mrr@10": 1.0, "query_count": 1},
    }
    with pytest.raises(AssertionError, match="recorded"):
        verify_system(system, qrels, "fixture")
