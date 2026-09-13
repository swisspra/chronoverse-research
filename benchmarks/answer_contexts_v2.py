"""Round-2 answer contexts: fair lexical+dense baselines, a delivery ablation and a no-retrieval floor.

Round 1 ranked the vanilla arms with bare MiniLM cosine while the Chronoverse arms
ranked with the application's hybrid lexical/vector/graph score. That confounded
retrieval quality with temporal semantics. Round 2 therefore gives the vanilla arms
the same lexical signal, renormalised without the graph term they cannot compute:

    A2  hybrid lexical+dense retrieval, no temporal projection
    B   long context: every version and notice for the question's entity (unchanged)
    C2  A2 top-50 reordered by the same local cross-encoder
    D   ledger-global lifecycle projection, then a delivery post-filter
    D2  delivery projection: lifecycle from received notices only (assertion level)
    E   delivery projection plus the explicit item view (unchanged)
    Z   no retrieval at all, question only

Round-1 modules, artifacts and hashes are untouched; everything here is imported.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from benchmarks.answer_experiment import PROMPT
from benchmarks.answer_contexts import (SEED, load, catalog, candidate_inventory, entity_context,
                                        pilot_queries, query_input, scoring_metadata, serialize_context)
from benchmarks.provenance import BenchmarkRun, add_provenance_argument, sha256

ROOT = Path(__file__).resolve().parents[1]
ARMS = ('A2', 'B', 'C2', 'D', 'D2', 'E', 'Z')
LEXICAL_WEIGHT = 0.35
VECTOR_WEIGHT = 0.65
METHOD_FOR_ARM = {'D': 'Filter after projection', 'D2': 'Delivery projection',
                  'E': 'Delivery explicit item view'}


def tokens(text):
    """Same tokenisation the application's lexical index uses."""
    return re.findall(r'[^\W_]+', text.casefold(), re.UNICODE)


def lexical_scores(question, texts):
    """Proportion of distinct question tokens present in the candidate text."""
    query = set(tokens(question))
    if not query:
        return [0.0] * len(texts)
    return [len(query & set(tokens(text))) / len(query) for text in texts]


def rank_candidates_v2(units, queries, cache_dir):
    """Hybrid lexical+dense top-50 for A2, then cross-encoder reordering for C2."""
    import torch
    from sentence_transformers import SentenceTransformer, CrossEncoder
    if not torch.backends.mps.is_available():
        raise RuntimeError('Frozen context runtime requires local MPS; no silent runtime switch.')
    dense = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', device='mps',
                                cache_folder=str(cache_dir), local_files_only=True)
    dense.max_seq_length = 256
    texts = [u['text'] for u in units]
    vectors = dense.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    qvectors = dense.encode([q['question'] for q in queries], batch_size=32,
                            normalize_embeddings=True, show_progress_bar=False)
    ids = [u['id'] for u in units]
    cross = CrossEncoder('cross-encoder/ms-marco-MiniLM-L6-v2', device='mps',
                         cache_folder=str(cache_dir), max_length=512, local_files_only=True)
    pools, reranked, components = {}, {}, {}
    for q, qvector in zip(queries, qvectors, strict=True):
        vector = vectors @ qvector
        lexical = lexical_scores(q['question'], texts)
        hybrid = [LEXICAL_WEIGHT * lexical[i] + VECTOR_WEIGHT * float(vector[i]) for i in range(len(ids))]
        positions = sorted(range(len(ids)), key=lambda i: (-hybrid[i], ids[i]))[:50]
        logits = cross.predict([(q['question'], texts[i]) for i in positions], batch_size=16,
                               show_progress_bar=False, activation_fn=torch.nn.Identity())
        pools[q['id']] = [ids[i] for i in positions]
        reranked[q['id']] = [ids[i] for i, s in sorted(zip(positions, logits),
                                                       key=lambda pair: (-float(pair[1]), ids[pair[0]]))]
        components[q['id']] = {ids[i]: {'lexical': round(lexical[i], 6), 'vector': round(float(vector[i]), 6),
                                        'hybrid': round(hybrid[i], 6)} for i in positions[:5]}
    torch.mps.synchronize()
    return pools, reranked, components


def build_manifests_v2(fixture, result, queries, pools, reranked, components):
    assertions, items, owners, receipts = catalog(fixture)
    by_id = {u['id']: u for u in candidate_inventory(fixture)}
    out, trace = [], {}
    for q in queries:
        public = query_input(q)
        qid = q['id']
        a_ids, c_ids = pools[qid], reranked[qid]
        if len(a_ids) != 50 or len(c_ids) != 50 or len(set(a_ids)) != 50 or set(a_ids) != set(c_ids):
            raise ValueError('C2 must reorder exactly the A2 top50.')
        b_rows, b_events, entity = entity_context(public['question'], assertions, fixture['events'])
        raw = {'A2': [row for aid in a_ids[:5] for row in by_id[aid]['rows']],
               'B': b_rows,
               'C2': [row for aid in c_ids[:5] for row in by_id[aid]['rows']],
               'Z': []}
        for arm, method in METHOD_FOR_ARM.items():
            raw[arm] = result['methods'][method]['per_query'][qid]['results']
        contexts = {arm: serialize_context(rows, b_events if arm == 'B' else [], public, receipts,
                                           bounded_receipts=arm in ('D', 'D2', 'E'))
                    for arm, rows in raw.items()}
        metadata = scoring_metadata(q, items, owners, receipts)
        for arm in ARMS:
            out.append({'query_id': qid, 'arm': arm, 'question': public['question'],
                        'recipient_id': public['recipient_id'],
                        **{k: public['scope'][k] for k in ('valid_at', 'known_at', 'received_by')},
                        'context': contexts[arm], 'prompt_sha256': sha256(PROMPT), **metadata})
        trace[qid] = {'hybrid_top50': a_ids, 'cross_encoder_top50': c_ids, 'B_question_entity': entity,
                      'top5_score_components': components[qid],
                      'context_ids': {arm: [r['id'] for r in context] for arm, context in contexts.items()}}
    return out, trace


def main():
    parser = add_provenance_argument(argparse.ArgumentParser(description=__doc__))
    parser.add_argument('--fixture', type=Path, default=ROOT / 'benchmarks/data/delivery-v3.json.gz')
    parser.add_argument('--results', type=Path, default=ROOT / 'docs/benchmarks-delivery-v3/results.json')
    parser.add_argument('--size', type=int, choices=(50, 500), default=50)
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'docs/benchmarks-next/answer-contexts-v2-50.jsonl')
    args = parser.parse_args()
    run_context = BenchmarkRun(allow_dirty=args.allow_dirty)
    inputs = {path: sha256(path) for path in (args.fixture, args.results, PROMPT)}
    artifacts = {p: sha256(p)
                 for folder in ('models--sentence-transformers--all-MiniLM-L6-v2',
                                'models--cross-encoder--ms-marco-MiniLM-L6-v2')
                 for p in (ROOT / '.model-cache/mps' / folder / 'snapshots').rglob('*') if p.is_file()}
    if not artifacts:
        raise RuntimeError('Local model artifact snapshots are missing; no implicit download.')
    fixture = load(args.fixture)
    result = load(args.results)
    if result['status'] != 'complete':
        raise ValueError('Actual delivery results must be complete.')
    if result.get('fixture_sha256') != sha256(args.fixture):
        raise ValueError('Retrieval result fixture hash does not match the supplied fixture.')
    missing = [m for m in METHOD_FOR_ARM.values() if m not in result['methods']]
    if missing:
        raise ValueError(f'Retrieval result is missing required methods: {missing}')
    queries = pilot_queries(fixture['queries'], args.size)
    recorded = {q['id']: q for q in result['query_manifest']}
    if any(recorded.get(q['id']) != q for q in queries):
        raise ValueError('Selected query metadata differs from the frozen retrieval query manifest.')
    units = candidate_inventory(fixture)
    pools, reranked, components = rank_candidates_v2(units, [query_input(q) for q in queries],
                                                     ROOT / '.model-cache/mps')
    rows, trace = build_manifests_v2(fixture, result, queries, pools, reranked, components)
    body = ''.join(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n' for row in rows)
    manifest = {'status': 'complete', 'round': 2, 'arms': list(ARMS), 'query_count': len(queries),
                'row_count': len(rows), 'selection_seed': SEED,
                'selected_query_ids': [q['id'] for q in queries],
                'selected_families': dict(Counter(q['family'] for q in queries)),
                'manifest_sha256': hashlib.sha256(body.encode()).hexdigest(),
                'fixture_sha256': sha256(args.fixture), 'retrieval_result_sha256': sha256(args.results),
                'prompt_sha256': sha256(PROMPT), 'trace': trace,
                'models': {'dense': 'all-MiniLM-L6-v2 FP32 MPS max_seq_length256',
                           'cross_encoder': 'ms-marco-MiniLM-L6-v2 FP32 MPS max_length512'},
                'ranking': {'formula': f'{LEXICAL_WEIGHT} * lexical + {VECTOR_WEIGHT} * cosine',
                            'lexical_definition': 'proportion of distinct question tokens present in the candidate text',
                            'why': 'Round 1 ranked A/C with bare cosine while D/E used the application hybrid score, '
                                   'confounding retrieval quality with temporal semantics. The graph term of the '
                                   'application score cannot be computed outside the Store, so the remaining two '
                                   'weights are renormalised and that difference is disclosed rather than hidden.'},
                'model_artifact_sha256': {str(p.relative_to(ROOT / '.model-cache/mps')): value
                                          for p, value in artifacts.items()},
                'arm_sources': {'A2': 'hybrid lexical+dense top5', 'B': 'question-entity all versions and notices',
                                'C2': 'A2 top50 reordered by cross-encoder, top5',
                                **{arm: f"recorded rows of method '{method}'" for arm, method in METHOD_FOR_ARM.items()},
                                'Z': 'empty context, question only'},
                'selection': 'Gold is added only after every arm context is assembled.'}
    if any(sha256(path) != expected for path, expected in inputs.items()):
        raise RuntimeError('Fixture, retrieval results or prompt changed during context assembly.')
    if any(sha256(path) != expected for path, expected in artifacts.items()):
        raise RuntimeError('Local model artifact changed during context assembly.')
    receipt = run_context.write_bytes(args.output, body.encode())
    manifest['jsonl_write_provenance'] = receipt['provenance']
    run_context.write_json(args.output.with_suffix('.manifest.json'), manifest)
    print(json.dumps({'output': str(args.output), 'rows': len(rows),
                      'sha256': manifest['manifest_sha256'], 'arms': list(ARMS)}))


if __name__ == '__main__':
    main()
