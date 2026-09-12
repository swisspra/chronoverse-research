"""Run stock Chronoverse and independent scoped/unscoped retrieval baselines."""
from __future__ import annotations
from benchmarks.provenance import BenchmarkRun, add_provenance_argument
import argparse
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import importlib.metadata
import json
import os
import platform
import time

from benchmarks.metrics import aggregate_metrics, latency_summary, reciprocal_rank_fusion


def instant(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result


def reference_eligible(assertion, scope, events):
    """Independent coordinate filter; never examines gold relevance labels."""
    valid, known = instant(scope['valid_at']), instant(scope['known_at'])
    if any(scope[key] != 'all' and assertion[key] != scope[key] for key in ('world', 'plane', 'perspective')):
        return False
    if instant(assertion['recorded_at']) > known or instant(assertion['valid_from']) > valid:
        return False
    if assertion['valid_to'] and valid >= instant(assertion['valid_to']):
        return False
    for event in events.get(assertion['id'], []):
        if instant(event['recorded_at']) <= known and instant(event['effective_at']) <= valid:
            # This fixture permits one retirement transition per target assertion.
            if event['type'] in ('correct', 'retract', 'supersede'):
                return False
    return True


def summarize_run(run, fixture, latencies=None):
    queries = fixture['queries']
    gold = {q['id']: {aid: 1 for aid in q['gold_assertion_ids']} for q in queries if q['gold_assertion_ids']}
    events = defaultdict(list)
    for event in fixture['events']:
        events[event['assertion_id']].append(event)
    by_id = {a['id']: a for a in fixture['assertions']}
    violations, total_returned, empty_correct, exact, precisions = 0, 0, 0, 0, []
    violating_queries = 0
    for query in queries:
        ranked = list(dict.fromkeys(run.get(query['id'], [])))[:10]
        relevant = set(query['gold_assertion_ids'])
        bad = sum(aid not in by_id or not reference_eligible(by_id[aid], query['scope'], events) for aid in ranked)
        violations += bad
        violating_queries += bool(bad)
        total_returned += len(ranked)
        if not relevant:
            empty_correct += not ranked
        else:
            precisions.append(len(relevant.intersection(ranked))/len(ranked) if ranked else 0.0)
        exact += set(ranked) == relevant
    empties = len(queries)-len(gold)
    groups = {}
    for category in sorted({q['category'] for q in queries}):
        part = [q for q in queries if q['category'] == category]
        part_gold = {q['id']: {aid: 1 for aid in q['gold_assertion_ids']} for q in part if q['gold_assertion_ids']}
        groups[category] = aggregate_metrics(run, part_gold)
        groups[category]['total_queries'] = len(part)
        groups[category]['empty_answer_rate'] = sum(not run.get(q['id']) for q in part)/len(part)
    return {**aggregate_metrics(run, gold), 'total_query_count': len(queries), 'empty_gold_count': empties,
        'empty_gold_abstention_rate': empty_correct/empties if empties else None,
        'returned_set_precision@10_answerable': sum(precisions)/len(precisions) if precisions else None,
        'exact_set@10_all_queries': exact/len(queries),
        'coordinate_ineligible_fraction@10': violations/total_returned if total_returned else 0.0,
        'queries_with_coordinate_violation@10': violating_queries/len(queries),
        'returned_count': total_returned,
        'latency': latency_summary(latencies or []), 'categories': groups}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture', type=Path, default=Path('benchmarks/data/temporal-v1.json'))
    parser.add_argument('--output', type=Path, default=Path('docs/benchmarks/temporal-results.json'))
    parser.add_argument('--repeats', type=int, default=3)
    add_provenance_argument(parser)
    args = parser.parse_args()
    benchmark_run = BenchmarkRun(allow_dirty=args.allow_dirty)
    import numpy as np
    from rank_bm25 import BM25Okapi
    from chronoverse.models import AssertionInput, EventInput, QueryRequest
    from chronoverse.store import Store, _text, _tokens
    from chronoverse import semantic
    os.environ['CHRONOVERSE_EMBEDDINGS'] = 'semantic'
    fixture = json.loads(args.fixture.read_text())
    records = sorted(fixture['assertions'], key=lambda row: row['id'])
    ids = [row['id'] for row in records]
    events = defaultdict(list)
    for event in fixture['events']:
        events[event['assertion_id']].append(event)

    started = time.perf_counter()
    store = Store(':memory:', seed=False)
    for row in records:
        store.add_assertion(AssertionInput(**row))
    for event in fixture['events']:
        store.add_event(event['assertion_id'], EventInput(**{k:v for k,v in event.items() if k != 'assertion_id'}))
    ledger_seconds = time.perf_counter()-started
    texts = [_text(row) for row in records]
    started = time.perf_counter()
    bm25 = BM25Okapi([_tokens(text) for text in texts])
    bm25_seconds = time.perf_counter()-started
    started = time.perf_counter()
    vectors = np.asarray([semantic._embed(text) for text in texts])
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    embedding_seconds = time.perf_counter()-started
    # Warm repeats are intentionally a cached-query measurement for EVERY system.
    started = time.perf_counter()
    for query in fixture['queries']:
        semantic._embed(query['query'])
    query_warmup_seconds = time.perf_counter()-started
    def ranks(query, method, scoped):
        allowed = [i for i,row in enumerate(records) if not scoped or reference_eligible(row, query['scope'], events)]
        if method in ('bm25', 'rrf'):
            lexical = bm25.get_scores(_tokens(query['query']))
            bm = sorted(allowed, key=lambda i: (-lexical[i], ids[i]))
        if method in ('dense', 'rrf'):
            vector = np.asarray(semantic._embed(query['query']))
            scores = vectors @ (vector / np.linalg.norm(vector))
            dense = sorted(allowed, key=lambda i: (-scores[i], ids[i]))
        if method == 'rrf':
            return reciprocal_rank_fusion([[ids[i] for i in bm], [ids[i] for i in dense]], k=60, limit=10)
        return [ids[i] for i in (bm if method == 'bm25' else dense)[:10]]

    methods = {
        'BM25': lambda q: ranks(q, 'bm25', False),
        'Dense MiniLM': lambda q: ranks(q, 'dense', False),
        'RRF hybrid': lambda q: ranks(q, 'rrf', False),
        'BM25 + reference scope/time filter': lambda q: ranks(q, 'bm25', True),
        'Dense + reference scope/time filter': lambda q: ranks(q, 'dense', True),
        'RRF + reference scope/time filter': lambda q: ranks(q, 'rrf', True),
        'Chronoverse stock': lambda q: [a['id'] for a in store.query(QueryRequest(query=q['query'], **q['scope'], limit=10))['results']],
    }
    results = {}
    try:
        for name, retrieve in methods.items():
            run, timings = {}, []
            for repeat in range(args.repeats):
                for query in fixture['queries']:
                    started = time.perf_counter()
                    ranking = retrieve(query)
                    timings.append(time.perf_counter()-started)
                    if repeat:
                        assert ranking == run[query['id']], (name, query['id'], 'nondeterministic ranking')
                    else:
                        run[query['id']] = ranking
            summary = summarize_run(run, fixture, timings)
            results[name] = {'summary': summary, 'rankings': run}
            print(name, json.dumps({k:v for k,v in summary.items() if k not in ('categories',)}), flush=True)
    finally:
        store.close()
    payload = dict(track='generated-temporal-capability', fixture_sha256=sha256(args.fixture.read_bytes()).hexdigest(),
        created_at=datetime.now(timezone.utc).isoformat(), corpus_size=len(records), queries=len(fixture['queries']),
        scenario_templates=21, entity_instantiations=12, repeats=args.repeats,
        protocol='Structured assertions/events and exact query coordinates supplied. Same canonical text and MiniLM model. Filters independently implement metadata semantics, not relevance judgments. All document/query embeddings warmed before timed repetitions. Retrieval only; no answer generation.',
        scope_filter_note='Reference scoped baselines use the same supplied metadata and lifecycle events; they are engineered comparators, not native BM25 temporal support.',
        latency_note='Warm cached-query local timings on a shared laptop, not a dedicated throughput or cold-query benchmark. Different indexes naturally have different overhead. Small corpus fits unmodified production cache.',
        empty_note='Answerable metrics exclude 36 empty-gold queries. Empty-answer behavior and returned-set precision are separate; extra context is not automatically a wrong generated answer.',
        versions={p:importlib.metadata.version(p) for p in ('rank-bm25','fastembed','numpy','chronoverse')},
        platform=platform.platform(), model=semantic.MODEL,
        indexing_seconds={'ledger':ledger_seconds,'bm25':bm25_seconds,'document_embeddings_including_model_load':embedding_seconds,'query_cache_warmup':query_warmup_seconds},
        systems=results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    benchmark_run.write_json(args.output, payload)


if __name__ == '__main__':
    main()
