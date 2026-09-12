"""Append-only SQLite ledger and scope-first temporal retrieval projections."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from threading import RLock
from uuid import uuid4

from .models import AssertionInput, EventInput, QueryRequest, PLANES, DEFAULT_VALID, DEFAULT_KNOWN, now, timestamp


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _tokens(text):
    return re.findall(r"[^\W_]+", text.casefold(), re.UNICODE)


def _vector(tokens):
    vector = Counter()
    for token in tokens:
        digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
        vector[int.from_bytes(digest[:4], "big") % 256] += 1 if digest[4] % 2 else -1
    return vector


def _cosine(a, b):
    norm = math.sqrt(sum(v * v for v in a.values()) * sum(v * v for v in b.values()))
    return sum(v * b.get(k, 0) for k, v in a.items()) / norm if norm else 0.0


def _text(assertion):
    return " ".join([assertion["subject"], assertion["predicate"], assertion["object"], assertion["summary"], *[e["text"] for e in assertion["evidence"]]])


def _entity_keys(assertion):
    scope = (assertion["world"], assertion["plane"], assertion["perspective"])
    return {(*scope, assertion[field].casefold()) for field in ("subject", "object")}


def retrieval_metadata():
    if os.getenv("CHRONOVERSE_EMBEDDINGS") == "semantic":
        return {"name": "semantic-local", "description": "Local sentence-transformers/all-MiniLM-L6-v2 dense embeddings (384 dimensions), lexical overlap and one-hop graph signals. Scores measure relevance, not truth."}
    return {"name": "hashed-lexical", "description": "Deterministic 256-dimensional hashed lexical vectors, token overlap and one-hop graph signals. No pretrained semantic model. Scores measure relevance, not truth."}


class Store:
    def __init__(self, path, seed=True):
        self.path = str(path)
        if self.path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._vector_index = None
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=15)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS assertions (
                id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, payload TEXT NOT NULL,
                world TEXT NOT NULL, plane TEXT NOT NULL, perspective TEXT NOT NULL,
                valid_from TEXT NOT NULL, valid_to TEXT, recorded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, assertion_id TEXT NOT NULL REFERENCES assertions(id),
                request_hash TEXT NOT NULL, recorded_at TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS assertions_scope_time ON assertions(world, plane, perspective, recorded_at, valid_from);
            CREATE INDEX IF NOT EXISTS events_assertion_time ON events(assertion_id, recorded_at);
            CREATE TRIGGER IF NOT EXISTS assertions_no_update BEFORE UPDATE ON assertions BEGIN SELECT RAISE(ABORT, 'assertions are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS assertions_no_delete BEFORE DELETE ON assertions BEGIN SELECT RAISE(ABORT, 'assertions are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events are immutable'); END;
        """)
        if seed:
            from .seed import populate
            populate(self)

    def close(self):
        with self._lock:
            if self._vector_index is not None:
                self._vector_index.close()
            self._db.close()

    def _raw(self, assertion_id):
        row = self._db.execute("SELECT payload FROM assertions WHERE id=?", (assertion_id,)).fetchone()
        if not row:
            raise KeyError(f"Assertion {assertion_id} not found")
        return json.loads(row["payload"])

    def _events(self, assertion_id, known_at):
        rows = self._db.execute("SELECT payload FROM events WHERE assertion_id=? AND recorded_at<=? ORDER BY recorded_at,id", (assertion_id, known_at)).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def _project(self, raw, known_at, valid_at):
        result = dict(raw)
        result["evidence"] = [e for e in raw["evidence"] if e["recorded_at"] <= known_at]
        events = self._events(raw["id"], known_at)
        result["events"] = events
        result["status"] = "active"
        boundary = raw["valid_to"]
        for event in sorted(events, key=lambda e: (e["effective_at"], {"supersede": 0, "correct": 1, "retract": 2}[e["type"]], e["recorded_at"], e["id"])):
            if event["type"] == "supersede":
                boundary = min(boundary, event["effective_at"]) if boundary else event["effective_at"]
            if valid_at >= event["effective_at"]:
                result["status"] = {"supersede": "superseded", "correct": "corrected", "retract": "retracted"}[event["type"]]
        result["effective_valid_to"] = boundary
        result["score"] = 0.0
        result["score_breakdown"] = {"lexical": 0.0, "vector": 0.0, "graph": 0.0}
        result["explanation"] = f"{result['status'].capitalize()} in the requested valid-time and knowledge-time snapshot; evidence and events are filtered by knowledge time."
        return result

    def get_assertion(self, assertion_id, known_at=DEFAULT_KNOWN, valid_at=DEFAULT_VALID):
        known_at, valid_at = timestamp(known_at), timestamp(valid_at)
        with self._lock:
            raw = self._raw(assertion_id)
            if raw["recorded_at"] > known_at:
                raise KeyError(f"Assertion {assertion_id} was not known at the requested time")
            return self._project(raw, known_at, valid_at)

    def _insert_assertion(self, value: AssertionInput):
        data = value.model_dump()
        request_hash = _fingerprint(data)
        assertion_id = value.id or f"a-{uuid4().hex}"
        existing = self._db.execute("SELECT request_hash,payload FROM assertions WHERE id=?", (assertion_id,)).fetchone()
        if existing:
            if existing["request_hash"] != request_hash:
                raise ValueError(f"Assertion {assertion_id} already exists with a different payload")
            raw = json.loads(existing["payload"])
            return self._project(raw, max(now(), raw["recorded_at"]), raw["valid_from"])
        recorded_at = value.recorded_at or now()
        data.update(id=assertion_id, recorded_at=recorded_at)
        for i, evidence in enumerate(data["evidence"]):
            evidence["id"] = f"{assertion_id}-e{i + 1}"
            evidence["recorded_at"] = evidence["recorded_at"] or recorded_at
        self._db.execute("INSERT INTO assertions VALUES (?,?,?,?,?,?,?,?,?)", (assertion_id, request_hash, _json(data), data["world"], data["plane"], data["perspective"], data["valid_from"], data["valid_to"], recorded_at))
        return self._project(data, max(now(), recorded_at), data["valid_from"])


    def add_assertion(self, value: AssertionInput):
        value = value if isinstance(value, AssertionInput) else AssertionInput.model_validate(value)
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            return self._insert_assertion(value)

    def add_assertions_atomic(self, values):
        """Import validated assertions in one transaction; any conflict rolls back all rows."""
        values = [value if isinstance(value, AssertionInput) else AssertionInput.model_validate(value) for value in values]
        if not values or len(values) > 500:
            raise ValueError("An import must contain 1–500 assertions")
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            before = self._db.execute("SELECT COUNT(*) FROM assertions").fetchone()[0]
            ids = [self._insert_assertion(value)["id"] for value in values]
            inserted = self._db.execute("SELECT COUNT(*) FROM assertions").fetchone()[0] - before
            return {"assertion_ids":ids,"inserted_count":inserted,"existing_count":len(ids)-inserted}

    def add_event(self, assertion_id, value: EventInput):
        value = value if isinstance(value, EventInput) else EventInput.model_validate(value)
        data = value.model_dump()
        request_hash = _fingerprint({"assertion_id": assertion_id, **data})
        event_id = value.id or f"ev-{uuid4().hex}"
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            existing = self._db.execute("SELECT request_hash,payload FROM events WHERE id=?", (event_id,)).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise ValueError(f"Event {event_id} already exists with a different payload")
                return json.loads(existing["payload"])
            target = self._raw(assertion_id)
            recorded_at = value.recorded_at or now()
            if recorded_at < target["recorded_at"]:
                raise ValueError("Event recorded_at cannot precede assertion recorded_at")
            if value.effective_at < target["valid_from"]:
                raise ValueError("Event effective_at cannot precede assertion valid_from")
            if value.replacement_id:
                replacement = self._raw(value.replacement_id)
                if assertion_id == value.replacement_id:
                    raise ValueError("An assertion cannot replace itself")
                if any(target[key] != replacement[key] for key in ("world", "plane", "perspective", "subject", "predicate")):
                    raise ValueError("Replacement must have the same scope, subject and predicate")
                if replacement["recorded_at"] > recorded_at:
                    raise ValueError("Replacement must be known when event is recorded")
                if replacement["valid_from"] > value.effective_at or (replacement["valid_to"] is not None and replacement["valid_to"] <= value.effective_at):
                    raise ValueError("replacement valid interval must cover event effective_at")
                # Lifecycle lineage is a directed acyclic graph; reversal needs a new assertion.
                pending, visited = [value.replacement_id], set()
                while pending:
                    current = pending.pop()
                    if current == assertion_id:
                        raise ValueError("Replacement would introduce a lifecycle cycle")
                    if current in visited:
                        continue
                    visited.add(current)
                    for row in self._db.execute("SELECT payload FROM events WHERE assertion_id=?", (current,)):
                        successor = json.loads(row["payload"]).get("replacement_id")
                        if successor:
                            pending.append(successor)
                if self._project(replacement, recorded_at, value.effective_at)["status"] != "active":
                    raise ValueError("replacement must be active at the event effective/recorded snapshot")
                if value.type == "supersede":
                    prior = self._db.execute("SELECT payload FROM events WHERE assertion_id=?", (assertion_id,)).fetchall()
                    if any(json.loads(row["payload"])["type"] == "supersede" for row in prior):
                        raise ValueError("Assertion is already superseded; append changes to its replacement")
            data.update(id=event_id, assertion_id=assertion_id, recorded_at=recorded_at)
            self._db.execute("INSERT INTO events VALUES (?,?,?,?,?)", (event_id, assertion_id, request_hash, recorded_at, _json(data)))
            return data

    def _eligible(self, request):
        conditions, params = ["recorded_at<=?", "valid_from<=?", "(valid_to IS NULL OR valid_to>?)"], [timestamp(request.known_at), timestamp(request.valid_at), timestamp(request.valid_at)]
        for field in ("world", "plane", "perspective"):
            value = getattr(request, field)
            if value != "all":
                conditions.append(f"{field}=?")
                params.append(value)
        rows = self._db.execute("SELECT payload FROM assertions WHERE " + " AND ".join(conditions) + " ORDER BY id", params).fetchall()
        projected = [self._project(json.loads(row["payload"]), timestamp(request.known_at), timestamp(request.valid_at)) for row in rows]
        return [a for a in projected if request.include_retired or (a["status"] == "active" and (a["effective_valid_to"] is None or timestamp(request.valid_at) < a["effective_valid_to"]))]

    def query(self, request: QueryRequest):
        request = request if isinstance(request, QueryRequest) else QueryRequest.model_validate(request)
        with self._lock:
            candidates = self._eligible(request)
        texts = [_text(a) for a in candidates]
        query_tokens = set(_tokens(request.query))
        query_vector = _vector(query_tokens)
        semantic = os.getenv("CHRONOVERSE_EMBEDDINGS") == "semantic"
        if semantic and query_tokens and candidates:
            from .semantic import score_texts
            from .vector_index import VectorIndex
            with self._lock:
                if self._vector_index is None:
                    self._vector_index = VectorIndex(self.path)
                index = self._vector_index
            vector_scores = score_texts(request.query, texts, index=index)
        else:
            vector_scores = [_cosine(query_vector, _vector(_tokens(text))) for text in texts]
        lexical_scores = [len(query_tokens & set(_tokens(text))) / len(query_tokens) if query_tokens else 0.0 for text in texts]
        anchors = set()
        direct = []
        for i, assertion in enumerate(candidates):
            matched = not query_tokens or lexical_scores[i] > 0 or (semantic and vector_scores[i] >= 0.28)
            direct.append(matched)
            if matched and query_tokens:
                anchors.update(_entity_keys(assertion))
        ranked = []
        for i, assertion in enumerate(candidates):
            graph = float(bool(anchors & _entity_keys(assertion))) if query_tokens else 0.0
            if not direct[i] and not graph:
                continue
            vector = max(0.0, float(vector_scores[i]))
            assertion["score_breakdown"] = {"lexical": round(lexical_scores[i], 4), "vector": round(vector, 4), "graph": graph}
            assertion["score"] = round(0.35 * lexical_scores[i] + 0.50 * vector + 0.15 * graph, 4)
            assertion["explanation"] += " Relevance = 0.35 × lexical + 0.50 × vector + 0.15 × graph; one-hop graph support is computed only inside the eligible scope."
            ranked.append(assertion)
        ranked.sort(key=lambda a: (-a["score"], a["id"]))
        # Conflicts derive from all relevant eligible assertions before display truncation.
        grouped = defaultdict(list)
        for assertion in ranked:
            if assertion["status"] == "active":
                grouped[(assertion["world"], assertion["plane"], assertion["perspective"], assertion["subject"], assertion["predicate"])].append(assertion)
        conflicts = []
        for key, group in grouped.items():
            objects = sorted({a["object"] for a in group})
            if len(objects) > 1:
                conflicts.append({"subject": key[3], "predicate": key[4], "assertion_ids": [a["id"] for a in group], "objects": objects, "explanation": "Multiple active objects in the same world, plane, perspective and time snapshot. No canonical winner is inferred; this is a potential conflict (some predicates permit multiple values)."})
        results = ranked[:request.limit]
        nodes, edges = {}, []
        for assertion in results:
            identity_scope = [assertion["world"], assertion["plane"], assertion["perspective"]]
            source = "entity-" + _fingerprint([*identity_scope, assertion["subject"]])[:16]
            target = "entity-" + _fingerprint([*identity_scope, assertion["object"]])[:16]
            nodes[source] = {"id": source, "label": assertion["subject"], "kind": "entity"}
            nodes[target] = {"id": target, "label": assertion["object"], "kind": "entity"}
            edges.append({"id": assertion["id"], "source": source, "target": target, "label": assertion["predicate"], "assertion_id": assertion["id"], "plane": assertion["plane"], "status": assertion["status"]})
        scope = {field: getattr(request, field) for field in ("valid_at", "known_at", "world", "plane", "perspective")}
        scope.update(valid_at=timestamp(request.valid_at), known_at=timestamp(request.known_at))
        return {"query": request.query, "scope": scope, "results": results, "conflicts": conflicts, "graph": {"nodes": list(nodes.values()), "edges": edges}, "explanation": f"Filtered {len(candidates)} eligible assertions by world, plane, perspective, valid time and knowledge time before retrieval. Returned {len(results)} of {len(ranked)} relevant assertions. Conflicts are preserved; score is not truth. Intervals are half-open; include_retired is {str(request.include_retired).lower()}.", "eligible_count": len(candidates), "retrieval": retrieval_metadata()}

    def meta(self, known_at=DEFAULT_KNOWN):
        known_at = timestamp(known_at)
        with self._lock:
            rows = self._db.execute("SELECT DISTINCT world,plane,perspective FROM assertions WHERE recorded_at<=?", (known_at,)).fetchall()
            counts = {table: self._db.execute(f"SELECT COUNT(*) FROM {table} WHERE recorded_at<=?", (known_at,)).fetchone()[0] for table in ("assertions", "events")}
        return {"worlds": sorted({r["world"] for r in rows}), "planes": PLANES, "perspectives": sorted({r["perspective"] for r in rows}), "defaults": {"valid_at": DEFAULT_VALID, "known_at": DEFAULT_KNOWN, "world": "main", "plane": "all", "perspective": "all"}, "counts": counts, "retrieval": retrieval_metadata(), "examples": [
            {"label": "Changing facts", "query": "Harbor director", "valid_at": DEFAULT_VALID, "known_at": DEFAULT_KNOWN, "plane": "fact", "world": "main", "perspective": "all"},
            {"label": "News before correction", "query": "Meridian injured", "valid_at": "2026-09-01", "known_at": "2026-09-02", "plane": "report", "world": "main", "perspective": "all"},
            {"label": "News after correction", "query": "Meridian injured", "valid_at": "2026-09-01", "known_at": "2026-09-04", "plane": "report", "world": "main", "perspective": "all"},
            {"label": "Earth: fact and belief", "query": "Earth shape", "valid_at": DEFAULT_VALID, "known_at": DEFAULT_KNOWN, "plane": "all", "world": "main", "perspective": "all"},
            {"label": "Scientific theories", "query": "gravity model", "valid_at": DEFAULT_VALID, "known_at": DEFAULT_KNOWN, "plane": "theory", "world": "main", "perspective": "all"},
        ]}

    def evaluate(self):
        from .seed import EVALUATION_CASES
        # Isolated, deterministic fixture evaluation does not include users' added data.
        fixture = Store(":memory:", seed=True)
        try:
            cases = []
            with fixture._lock:
                raw = [json.loads(r["payload"]) for r in fixture._db.execute("SELECT payload FROM assertions ORDER BY id")]
            for case in EVALUATION_CASES:
                request = QueryRequest(**case["request"], limit=100)
                result = fixture.query(request)
                actual = {a["id"] for a in result["results"]}
                # Unscoped lexical baseline deliberately omits temporal and epistemic constraints.
                baseline = {a["id"] for a in raw if set(_tokens(request.query)) & set(_tokens(_text(a)))}
                expected, forbidden = set(case["expected"]), set(case["forbidden"])
                cases.append({"name": case["name"], "query": request.model_dump(), "expected_ids": sorted(expected), "forbidden_ids": sorted(forbidden), "baseline_ids": sorted(baseline), "chronoverse_ids": sorted(actual), "baseline_pass": expected <= baseline and not (forbidden & baseline), "chronoverse_pass": expected <= actual and not (forbidden & actual), "explanation": case["explanation"]})
            return {"dataset": "Chronoverse synthetic temporal-gates-v1", "disclaimer": "Controlled synthetic scope/temporal correctness examples, not a general retrieval quality benchmark. Baseline is unscoped lexical retrieval, not a full GraphRAG implementation. Real-world accuracy requires representative labeled data.", "cases": cases, "summary": {"cases": len(cases), "baseline_passed": sum(c["baseline_pass"] for c in cases), "chronoverse_passed": sum(c["chronoverse_pass"] for c in cases)}}
        finally:
            fixture.close()
