"""Download model weights only; no document content is sent to the provider."""
from pathlib import Path
import os
from fastembed import TextEmbedding

root = Path(__file__).resolve().parents[1]
cache = os.environ.get('CHRONOVERSE_MODEL_CACHE', str(root / '.model-cache'))
model = TextEmbedding('sentence-transformers/all-MiniLM-L6-v2', cache_dir=cache, threads=2)
vector = next(iter(model.embed(['Chronoverse local model readiness check.'])))
print(f'Local semantic model ready: {len(vector)} dimensions. Cache: {cache}')
