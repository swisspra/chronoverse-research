import pytest
from chronoverse.models import QueryRequest
from chronoverse.store import Store,_text
from benchmarks.scifact import canonical_assertion, enlarged_embedding_cache


def test_canonical_text_is_exact_store_search_input():
    value=canonical_assertion({"_id":"123","title":"Scientific title","text":"Study abstract."})
    store=Store(":memory:",seed=False)
    try:
        row=store.add_assertion(value)
        assert _text(row) == "SciFact document 123 contains Abstract 123  Scientific title\nStudy abstract."
    finally:
        store.close()


def test_cache_wrapper_preserves_stock_outputs_and_restores_function(monkeypatch):
    from chronoverse import semantic
    from functools import lru_cache
    calls=[]
    @lru_cache(maxsize=2)
    def fake_embed(text):
        calls.append(text)
        return (float(len(text)),1.0)
    monkeypatch.setattr(semantic,"_embed",fake_embed)
    with enlarged_embedding_cache() as cached:
        assert cached("a") == fake_embed.__wrapped__("a")
        cached("bb"); cached("ccc"); cached("a")
        assert cached.cache_info().hits == 1
        assert semantic._embed is cached
    assert semantic._embed is fake_embed
