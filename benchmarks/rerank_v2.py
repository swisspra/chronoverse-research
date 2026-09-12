"""Fixed local cross-encoder experiment over complete SciFact RRF candidates.

No model training, test-label tuning, application data or production changes.
"""
from benchmarks.provenance import BenchmarkRun, add_provenance_argument
import argparse
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import argparse
import importlib.metadata
import os
import time

import numpy as np
from fastembed.rerank.cross_encoder import TextCrossEncoder
from fastembed.common.model_description import ModelSource
from rank_bm25 import BM25Okapi

from chronoverse import semantic
from chronoverse.store import _tokens
from benchmarks.scifact import download_dataset
from benchmarks.metrics import aggregate_metrics, metrics_for_query, reciprocal_rank_fusion, latency_summary, paired_bootstrap_difference

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'chronoverse/ms-marco-MiniLM-L6-v2-int8'
MODEL_SOURCE = 'Xenova/ms-marco-MiniLM-L-6-v2'
TOP_K = 50


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime', choices=['mps','onnx-int8'], default='mps')
    add_provenance_argument(parser);args=parser.parse_args();benchmark_run=BenchmarkRun(allow_dirty=args.allow_dirty)
    os.environ['CHRONOVERSE_MODEL_CACHE'] = str(ROOT / '.model-cache')
    folder = ROOT / '.benchmark-data/scifact'
    _, queries, qrels, hashes = download_dataset(folder)
    records = [json.loads(line) for line in (folder/'canonical-records.jsonl').read_text().splitlines()]
    ids = [r['doc_id'] for r in records]
    texts = [r['text'] for r in records]
    position = {aid: i for i, aid in enumerate(ids)}
    document_vectors = np.load(folder/'document-embeddings.npy')
    assert document_vectors.shape == (len(ids), 384)
    norms = np.linalg.norm(document_vectors, axis=1)
    bm25 = BM25Okapi([_tokens(text) for text in texts])
    setup = time.perf_counter()
    if args.runtime == 'mps':
        import torch
        from sentence_transformers import CrossEncoder
        if not torch.backends.mps.is_available():
            raise RuntimeError('MPS unavailable; select --runtime onnx-int8 explicitly.')
        model = CrossEncoder('cross-encoder/ms-marco-MiniLM-L6-v2', device='mps', cache_folder=str(ROOT/'.model-cache/mps'), max_length=512, local_files_only=True)
        def rerank(query, documents):
            output=model.predict([(query,text) for text in documents], batch_size=16, show_progress_bar=False, activation_fn=torch.nn.Identity())
            torch.mps.synchronize()
            return list(map(float,output))
        model_file='PyTorch safetensors, FP32, max_length=512'
        model_name='cross-encoder/ms-marco-MiniLM-L6-v2'
    else:
        TextCrossEncoder.add_custom_model(MODEL, ModelSource(hf=MODEL_SOURCE), model_file='onnx/model_quantized.onnx', license='apache-2.0')
        model = TextCrossEncoder(MODEL, cache_dir=str(ROOT/'.model-cache'), threads=2, local_files_only=True)
        def rerank(query, documents):
            return list(model.rerank(query,documents,batch_size=1))
        model_file='onnx/model_quantized.onnx'
        model_name=MODEL
    model_setup_seconds = time.perf_counter()-setup
    # Independent warm-up, not one of the judged queries.
    rerank('Search for relevant scientific evidence.', ['A study examines its evidence.'])
    output_dir = ROOT/'docs/benchmarks-v2'
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = output_dir/f'rerank-{args.runtime}-progress.json'
    fingerprint = {'runner_sha256':digest(Path(__file__)), 'canonical_sha256':digest(folder/'canonical-records.jsonl'),
                   'vectors_sha256':digest(folder/'document-embeddings.npy'), 'model':model_name, 'candidate_k':TOP_K, 'batch_size':16 if args.runtime=='mps' else 1, 'model_file':model_file, 'runtime':args.runtime}
    rows = []
    if checkpoint.exists():
        saved = json.loads(checkpoint.read_text())
        if saved['fingerprint'] == fingerprint:
            rows = saved['per_query']
    done = {row['id'] for row in rows}
    for qid, query in queries.items():
        if qid in done:
            continue
        started = time.perf_counter()
        lexical = bm25.get_scores(_tokens(query))
        # Bypass only the QUERY LRU for a fresh query encoding in each timing.
        vector = np.asarray(semantic._embed.__wrapped__(query))
        dense = document_vectors @ vector / np.maximum(norms*np.linalg.norm(vector), 1e-12)
        rank_bm25 = [ids[i] for i in sorted(range(len(ids)), key=lambda i: (-float(lexical[i]), ids[i]))]
        rank_dense = [ids[i] for i in sorted(range(len(ids)), key=lambda i: (-float(dense[i]), ids[i]))]
        candidates = reciprocal_rank_fusion([rank_bm25, rank_dense], k=60, limit=TOP_K)
        first_stage = time.perf_counter()-started
        started = time.perf_counter()
        scores = rerank(query, [texts[position[aid]] for aid in candidates])
        ranking = [aid for aid, score in sorted(zip(candidates, scores), key=lambda pair: (-float(pair[1]), pair[0]))]
        rerank_seconds = time.perf_counter()-started
        assert len(ranking) == TOP_K and set(ranking) == set(candidates)
        rows.append({'id':qid, 'query':query, 'candidates':candidates, 'reranked':ranking,
                     'cross_encoder_scores':dict(zip(candidates,map(float,scores))),
                     'first_stage_seconds':first_stage, 'rerank_seconds':rerank_seconds,
                     'total_seconds':first_stage+rerank_seconds})
        benchmark_run.write_json(checkpoint, {'fingerprint':fingerprint, 'per_query':rows})
        if len(rows)%25 == 0:
            print(json.dumps({'completed':len(rows),'total':len(queries)}), flush=True)
    by_id = {row['id']:row for row in rows}
    rows = [by_id[qid] for qid in queries]
    runs = {'rrf_minilm_top50':{row['id']:row['candidates'] for row in rows},
            'rrf_minilm_cross_encoder':{row['id']:row['reranked'] for row in rows}}
    methods = {name:{'metrics':aggregate_metrics(run,qrels)} for name,run in runs.items()}
    old = json.loads((ROOT/'docs/benchmarks/scifact-results.json').read_text())
    old_ndcg = old['methods']['rrf_bm25_dense']['metrics']['ndcg@10']
    new_ndcg = methods['rrf_minilm_top50']['metrics']['ndcg@10']
    if abs(new_ndcg-old_ndcg)>1e-9:
        raise AssertionError(f'First-stage reproduction changed: {new_ndcg} vs {old_ndcg}')
    for name, keys in [('rrf_minilm_top50',['first_stage_seconds']),('rrf_minilm_cross_encoder',['total_seconds'])]:
        methods[name]['latency'] = latency_summary([sum(row[key] for key in keys) for row in rows])
    differences = paired_bootstrap_difference(
        [metrics_for_query(runs['rrf_minilm_cross_encoder'][qid],qrels[qid])['ndcg@10'] for qid in queries],
        [metrics_for_query(runs['rrf_minilm_top50'][qid],qrels[qid])['ndcg@10'] for qid in queries])
    model_folder = ROOT/('.model-cache/mps/models--cross-encoder--ms-marco-MiniLM-L6-v2' if args.runtime=='mps' else '.model-cache/models--Xenova--ms-marco-MiniLM-L-6-v2')
    model_hashes = {str(p.relative_to(model_folder)):digest(p) for p in model_folder.rglob('*') if p.is_file() and 'snapshots' in p.parts}
    result = {'created_at':datetime.now(timezone.utc).isoformat(), 'dataset':'BEIR SciFact test', 'corpus_count':len(ids),
              'query_count':len(queries), 'parameters':fingerprint, 'model_hashes':model_hashes, 'dataset_hashes':hashes,
              'model_setup_seconds':model_setup_seconds, 'environment':{name:importlib.metadata.version(name) for name in ['numpy','fastembed','onnxruntime','rank-bm25']+(['torch','sentence-transformers','transformers'] if args.runtime=='mps' else [])}, 'methods':methods, 'paired_ndcg_difference':differences,
              'per_query':rows, 'protocol':'Fixed RRF k=60 over full BM25 and MiniLM rankings; fixed top50 candidates reranked with local MS MARCO MiniLM cross-encoder (runtime/precision explicitly recorded). No test-label tuning. Same canonical evidence as v1.',
              'limitations':['Only SciFact was reranked; domain transfer is unmeasured.',
                             'CPU FP32 and INT8 pilots were stopped for high latency under contention; no full CPU accuracy claim. Runtime choice was based on timing before relevance evaluation.',
                             'Pair encoding truncates to the model tokenizer limit; no long-document chunking.',
                             'Cross-encoder logits measure relevance, not confidence or truth.',
                             'Timings are shared-machine measurements; first-stage CPU and reranker runtime are explicit. Fresh query encoding and warm document vectors; indexing excluded.',
                             'Public test data exposure during model pretraining cannot be ruled out.'],
              'sources':['https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2','https://huggingface.co/Xenova/ms-marco-MiniLM-L-6-v2']}
    benchmark_run.write_json(output_dir/'rerank-results.json', result)
    print(json.dumps({'methods':methods,'paired_ndcg_difference':differences}),flush=True)


if __name__ == '__main__':
    main()
