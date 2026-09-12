"""Optional local ONNX embeddings. Document text never leaves this process.

Run scripts/download_model.py explicitly before enabling semantic retrieval.
The inference path only loads cached model files; it never downloads models.
"""
from functools import lru_cache
import os
import hashlib
from importlib.metadata import version
from pathlib import Path
from threading import RLock

MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
INFERENCE_BATCH_SIZE = 4
_lock = RLock()


def cache_path() -> str:
    return os.environ.get('CHRONOVERSE_MODEL_CACHE', str(Path(__file__).resolve().parents[2] / '.model-cache'))


@lru_cache(maxsize=1)
def _model():
    try:
        from fastembed import TextEmbedding
        return TextEmbedding(MODEL, cache_dir=cache_path(), threads=2, local_files_only=True)
    except Exception as exc:
        raise RuntimeError('Semantic model unavailable. Install the semantic extra and run scripts/download_model.py, or select lexical mode.') from exc


@lru_cache(maxsize=2048)
def _embed(text: str) -> tuple[float, ...]:
    with _lock:
        return tuple(float(v) for v in next(iter(_model().embed([text]))))


@lru_cache(maxsize=1)
def model_identity() -> tuple[str, int]:
    """Fingerprint the loaded model artifacts and preprocessing implementation.

    The model is immutable for this process lifetime. Restart after replacing
    cached model files; a new process hashes their contents before reusing rows.
    """
    model = _model().model
    directory = Path(model._model_dir)
    digest = hashlib.sha256(f"{MODEL}|fastembed={version('fastembed')}|inference-batch={INFERENCE_BATCH_SIZE}|raw-float64-v1".encode())
    for path in sorted(p for p in directory.rglob('*') if p.is_file()):
        digest.update(str(path.relative_to(directory)).encode())
        with path.open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
    return digest.hexdigest(), model.model_description.dim


def _encode_documents(texts: list[str]):
    with _lock:
        return list(_model().embed(texts, batch_size=INFERENCE_BATCH_SIZE))


def score_texts(query: str, texts: list[str], *, index=None) -> list[float]:
    """Cosine scores of normalized 384-dimensional MiniLM vectors."""
    if not texts:
        return []
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError('Semantic dependencies unavailable. Install the semantic extra or select lexical mode.') from exc
    q = np.asarray(_embed(query))
    if index is not None:
        model_id, dimensions = model_identity()
        return index.score(q, texts, model_id=model_id, dimensions=dimensions, encode=_encode_documents)
    qnorm = float(np.linalg.norm(q))
    scores = []
    for text in texts:
        vector = np.asarray(_embed(text))
        denominator = qnorm * float(np.linalg.norm(vector))
        scores.append(float(np.dot(q, vector) / denominator) if denominator else 0.0)
    return scores
