"""Rebuildable, bounded-memory vectors in the owning profile's SQLite database.

Only callers' already-scoped projected text enters this index. It stores no query
answers and never selects candidates; the immutable ledger remains authoritative.
"""
from __future__ import annotations
import hashlib
import sqlite3
from threading import RLock

VERSION = 1
CHUNK_SIZE = 256
ENCODE_BATCH_SIZE = 32


class VectorIndex:
    def __init__(self, path):
        self._lock = RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self._db.execute('PRAGMA journal_mode=WAL')
        self._db.execute('''CREATE TABLE IF NOT EXISTS derived_vectors (
            model_id TEXT NOT NULL, text_hash TEXT NOT NULL,
            dimensions INTEGER NOT NULL, version INTEGER NOT NULL,
            vector BLOB NOT NULL, checksum TEXT NOT NULL,
            PRIMARY KEY(model_id, text_hash)
        )''')
        self._db.commit()

    def close(self):
        with self._lock:
            self._db.close()

    def score(self, query_vector, texts, *, model_id, dimensions, encode):
        import numpy as np
        q = np.asarray(query_vector, dtype=np.float64)
        if q.shape != (dimensions,) or not np.isfinite(q).all():
            raise RuntimeError('Semantic query vector has invalid dimensions or values.')
        qnorm = float(np.linalg.norm(q))
        scores = []
        # One connection per Store; concurrent processes may redundantly encode a
        # missing chunk, but atomic UPSERTs publish only complete validated rows.
        with self._lock:
            for offset in range(0, len(texts), CHUNK_SIZE):
                chunk = texts[offset:offset + CHUNK_SIZE]
                keys = [hashlib.sha256(text.encode('utf-8')).hexdigest() for text in chunk]
                unique = dict(zip(keys, chunk))
                marks = ','.join('?' for _ in unique)
                rows = self._db.execute(f'''SELECT text_hash, dimensions, version, vector, checksum
                    FROM derived_vectors WHERE model_id=? AND text_hash IN ({marks})''',
                    [model_id, *unique]).fetchall()
                vectors = {}
                for key, size, version, blob, checksum in rows:
                    if (size != dimensions or version != VERSION or not isinstance(blob, bytes)
                            or len(blob) != dimensions * 8 or hashlib.sha256(blob).hexdigest() != checksum):
                        continue
                    vector = np.frombuffer(blob, dtype='<f8')
                    if np.isfinite(vector).all():
                        vectors[key] = vector
                missing = [key for key in unique if key not in vectors]
                for start in range(0, len(missing), ENCODE_BATCH_SIZE):
                    batch = missing[start:start + ENCODE_BATCH_SIZE]
                    encoded = list(encode([unique[key] for key in batch]))
                    if len(encoded) != len(batch):
                        raise RuntimeError('Semantic encoder returned an incomplete document batch.')
                    inserts = []
                    for key, value in zip(batch, encoded):
                        vector = np.asarray(value, dtype='<f8')
                        if vector.shape != (dimensions,) or not np.isfinite(vector).all():
                            raise RuntimeError('Semantic document vector has invalid dimensions or values.')
                        blob = vector.tobytes()
                        inserts.append((model_id, key, dimensions, VERSION, blob, hashlib.sha256(blob).hexdigest()))
                        vectors[key] = vector
                    with self._db:
                        self._db.executemany('INSERT OR REPLACE INTO derived_vectors VALUES (?,?,?,?,?,?)', inserts)
                matrix = np.stack([vectors[key] for key in keys])
                denominators = qnorm * np.linalg.norm(matrix, axis=1)
                dots = matrix @ q
                values = np.divide(dots, denominators, out=np.zeros(len(keys)), where=denominators != 0)
                scores.extend(float(value) for value in values)
        return scores
