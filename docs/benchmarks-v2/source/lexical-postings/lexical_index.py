"""One bounded, Store-owned exact-text cohort of unique-token postings.

This caches document tokenization only. Scope and temporal eligibility are always
computed by Store before scoring; any ordered projected-text change rebuilds it.
The byte limit covers retained Python cache objects, not caller text, transient
per-document tokenizer sets, result arrays, interpreter overhead or process RSS.
"""
from array import array
import hashlib
import sys
from threading import RLock

DEFAULT_LIMIT = 64 * 1024 * 1024


class _BudgetExceeded(Exception):
    pass


class LexicalIndex:
    def __init__(self, owner='', memory_limit=DEFAULT_LIMIT):
        if memory_limit < 4096:
            raise ValueError('Lexical cache memory limit must be at least 4096 bytes.')
        self.owner = str(owner)
        self.memory_limit = memory_limit
        self._lock = RLock()
        self._key = None
        self._rejected_key = None
        self._count = 0
        self._postings = {}

    def _fingerprint(self, texts):
        digest = hashlib.sha256()
        owner = self.owner.encode('utf-8')
        digest.update(len(owner).to_bytes(8, 'big'))
        digest.update(owner)
        digest.update(len(texts).to_bytes(8, 'big'))
        for text in texts:
            encoded = text.encode('utf-8')
            digest.update(len(encoded).to_bytes(8, 'big'))
            digest.update(encoded)
        return digest.digest()

    def _metadata_bytes(self):
        return (sys.getsizeof(self) + sys.getsizeof(self.__dict__)
                + sum(sys.getsizeof(k) for k in self.__dict__)
                + sum(sys.getsizeof(v) for k, v in self.__dict__.items() if k != '_postings'))

    @property
    def retained_bytes(self):
        with self._lock:
            return (self._metadata_bytes() + sys.getsizeof(self._postings)
                    + sum(sys.getsizeof(token) + sys.getsizeof(positions)
                          for token, positions in self._postings.items()))

    def statistics(self):
        with self._lock:
            return {'cached_documents': self._count, 'unique_tokens': len(self._postings),
                    'retained_bytes': self.retained_bytes, 'memory_limit_bytes': self.memory_limit,
                    'rejected_cohort': self._rejected_key is not None}

    def _clear(self, rejected=None):
        self._postings = {}
        self._count = 0
        self._key = None
        self._rejected_key = rejected

    def _build(self, key, texts, tokenize):
        # Release the previous cohort before allocating its replacement.
        self._clear()
        self._key, self._count = key, len(texts)
        base = self._metadata_bytes()
        token_bytes = array_bytes = 0
        try:
            if self._count >= 2 ** (8 * array('I').itemsize):
                raise _BudgetExceeded()
            for position, text in enumerate(texts):
                for token in set(tokenize(text)):
                    positions = self._postings.get(token)
                    if positions is None:
                        positions = array('I')
                        self._postings[token] = positions
                        token_bytes += sys.getsizeof(token)
                        array_bytes += sys.getsizeof(positions)
                    previous = sys.getsizeof(positions)
                    positions.append(position)
                    array_bytes += sys.getsizeof(positions) - previous
                    # Include dictionary resizing and array capacity growth, not
                    # merely the number of populated integer positions.
                    if base + sys.getsizeof(self._postings) + token_bytes + array_bytes > self.memory_limit:
                        raise _BudgetExceeded()
            if self.retained_bytes > self.memory_limit:
                raise _BudgetExceeded()
        except _BudgetExceeded:
            self._clear(rejected=key)
            return False
        except BaseException:
            self._clear()
            raise
        return True

    def score(self, query_tokens, texts, tokenize):
        query_tokens = set(query_tokens)
        if not query_tokens:
            return [0.0] * len(texts)
        if not texts:
            return []
        with self._lock:
            key = self._fingerprint(texts)
            usable = key == self._key
            if not usable and key != self._rejected_key:
                usable = self._build(key, texts, tokenize)
            denominator = len(query_tokens)
            if not usable:
                # Correct bounded fallback; never use a partial postings index.
                return [len(query_tokens & set(tokenize(text))) / denominator for text in texts]
            counts = array('I', [0]) * self._count
            for token in query_tokens:
                for position in self._postings.get(token, ()):
                    counts[position] += 1
            return [count / denominator for count in counts]
