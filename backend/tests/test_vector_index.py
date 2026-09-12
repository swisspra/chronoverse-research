"""Persistent vector behavior with deterministic cheap encoders, not model downloads."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import sqlite3
import numpy as np
import pytest

from chronoverse import semantic
from chronoverse.models import AssertionInput, QueryRequest
from chronoverse.store import Store


class Encoder:
    def __init__(self):
        self.documents = []
        self.batches = []

    def __call__(self, texts):
        self.documents.extend(texts)
        self.batches.append(len(texts))
        return [np.array([int(hashlib.sha256(t.encode()).hexdigest()[:4], 16) / 65536, 1., -0.25]) for t in texts]


def make_index(path):
    from chronoverse.vector_index import VectorIndex
    return VectorIndex(path)


def score(index, encoder, texts, model='fake-v1'):
    return index.score([1., 0., 0.], texts, model_id=model, dimensions=3, encode=encoder)


def test_more_than_lru_capacity_persists_across_reopen_without_document_encoding(tmp_path):
    path = tmp_path / 'ledger.db'
    texts = [f'document {i}' for i in range(2100)]
    encoder = Encoder()
    index = make_index(path)
    first = score(index, encoder, texts)
    assert len(first) == 2100 and len(encoder.documents) == 2100
    assert max(encoder.batches) <= 32
    assert score(index, encoder, texts) == first
    assert len(encoder.documents) == 2100
    index.close()
    reopened = make_index(path)
    assert score(reopened, encoder, texts) == first
    assert len(encoder.documents) == 2100
    reopened.close()


def test_model_and_exact_text_invalidation_and_duplicate_texts(tmp_path):
    index, encoder = make_index(tmp_path / 'ledger.db'), Encoder()
    result = score(index, encoder, ['old', 'old'])
    assert result[0] == result[1] and encoder.documents == ['old']
    score(index, encoder, ['old', 'new'])
    assert encoder.documents == ['old', 'new']
    score(index, encoder, ['old'], model='fake-v2')
    assert encoder.documents == ['old', 'new', 'old']
    index.close()


@pytest.mark.parametrize('assignment', ["vector=x'00'", 'dimensions=999', 'version=99', "checksum='wrong'"])
def test_corrupt_derived_row_rebuilds_without_changing_scores(tmp_path, assignment):
    path = tmp_path / 'ledger.db'
    index, encoder = make_index(path), Encoder()
    expected = score(index, encoder, ['old'])
    with sqlite3.connect(path) as db:
        db.execute('UPDATE derived_vectors SET ' + assignment)
    assert score(index, encoder, ['old']) == expected
    assert encoder.documents == ['old', 'old']
    index.close()


def test_exact_cosine_zero_negative_and_concurrent_connections(tmp_path):
    path = tmp_path / 'ledger.db'
    left, right = make_index(path), make_index(path)
    def encode(texts):
        return [{'same': [1., 0., 0.], 'opposite': [-1., 0., 0.], 'zero': [0., 0., 0.]}[t] for t in texts]
    def run(index):
        return score(index, encode, ['same', 'opposite', 'zero'])
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, [left, right] * 6))
    assert results == [[1., -1., 0.]] * 12
    left.close()
    right.close()


def test_store_index_uses_only_projected_evidence_and_sees_new_assertions(tmp_path, monkeypatch):
    monkeypatch.setenv('CHRONOVERSE_EMBEDDINGS', 'semantic')
    encoded = []
    def encode(texts):
        encoded.extend(texts)
        return [[1., 0., 0.] if 'late-secret' in text else [0., 1., 0.] for text in texts]
    monkeypatch.setattr(semantic, '_encode_documents', encode, raising=False)
    monkeypatch.setattr(semantic, 'model_identity', lambda: ('fixture-model', 3), raising=False)
    monkeypatch.setattr(semantic, '_embed', lambda text: (1., 0., 0.))
    store = Store(tmp_path / 'ledger.db', seed=False)
    store.add_assertion(AssertionInput(id='a', subject='Harbor', predicate='report', object='initial', valid_from='2026-01-01', recorded_at='2026-01-01', evidence=[{'title':'Early','text':'initial'}, {'title':'Later','text':'late-secret','recorded_at':'2026-05-01'}]))
    early = QueryRequest(query='late-secret', known_at='2026-04-01')
    late = QueryRequest(query='late-secret', known_at='2026-06-01')
    assert store.query(early)['results'] == []
    assert len(encoded) == 1 and 'late-secret' not in encoded[0]
    assert [r['id'] for r in store.query(late)['results']] == ['a']
    assert len(encoded) == 2 and 'late-secret' in encoded[1]
    assert store.query(early)['results'] == []
    assert len(encoded) == 2
    store.add_assertion(AssertionInput(id='b', subject='New', predicate='report', object='late-secret', valid_from='2026-01-01', recorded_at='2026-01-01', evidence=[{'title':'New','text':'fresh'}]))
    assert [r['id'] for r in store.query(early)['results']] == ['b']
    store.close()
    reopened = Store(tmp_path / 'ledger.db', seed=False)
    before = len(encoded)
    assert [r['id'] for r in reopened.query(late)['results']] == ['a', 'b']
    assert len(encoded) == before
    reopened.close()


def test_invalid_encoder_batch_never_publishes_partial_rows(tmp_path):
    path = tmp_path / 'ledger.db'
    index = make_index(path)
    for bad in ([[1., 0., 0.]], [[1., 0., 0.], [float('nan'), 0., 0.]]):
        with pytest.raises(RuntimeError):
            score(index, lambda texts: bad, ['one', 'two'])
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT COUNT(*) FROM derived_vectors').fetchone()[0] == 0
    index.close()


def test_model_fingerprint_changes_with_artifact_contents(tmp_path, monkeypatch):
    from types import SimpleNamespace
    artifact = tmp_path / 'model.onnx'
    artifact.write_bytes(b'first model')
    model = SimpleNamespace(model=SimpleNamespace(_model_dir=tmp_path, model_description=SimpleNamespace(dim=3)))
    monkeypatch.setattr(semantic, '_model', lambda: model)
    semantic.model_identity.cache_clear()
    try:
        first, dim = semantic.model_identity()
        assert dim == 3
        artifact.write_bytes(b'other model')
        semantic.model_identity.cache_clear()
        second, _ = semantic.model_identity()
        assert first != second
    finally:
        semantic.model_identity.cache_clear()
