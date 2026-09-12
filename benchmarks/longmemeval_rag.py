"""Gold-free LongMemEval-S vanilla dense contexts and separate session-qrel diagnostics."""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time

from benchmarks.provenance import BenchmarkRun,add_provenance_argument,sha256

ROOT=Path(__file__).resolve().parents[1]
DATA_SHA='d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442'
MODEL_REVISION='1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
MODEL_NAME='sentence-transformers/all-MiniLM-L6-v2'
MODEL_PATH=ROOT/'.model-cache/mps/models--sentence-transformers--all-MiniLM-L6-v2/snapshots'/MODEL_REVISION
MAX_TOKENS=256


def clock(value):
    # The dataset supplies a calendar clock without timezone semantics. Compare
    # its stated clock consistently; do not invent UTC or recipient delivery.
    return datetime.strptime(value,'%Y/%m/%d (%a) %H:%M')


def public_ingress(row):
    return {'question_id':row['question_id'],'question':row['question'],'question_date':row['question_date'],
        'sessions':[{'id':sid,'date':date,'turns':[{'role':t['role'],'content':t['content']} for t in turns]}
                    for sid,date,turns in zip(row['haystack_session_ids'],row['haystack_dates'],row['haystack_sessions'],strict=True)]}


def split_text(text,tokenizer,max_tokens=MAX_TOKENS):
    special=tokenizer.num_special_tokens_to_add(pair=False);budget=max_tokens-special
    if budget<1:raise ValueError('Token budget must exceed special tokens')
    encoded=tokenizer(text,add_special_tokens=False,return_offsets_mapping=True,truncation=False)
    offsets=encoded['offset_mapping']
    if not offsets:return []
    chunks=[];start_token=0;start_char=0
    while start_token<len(offsets):
        end_token=min(start_token+budget,len(offsets))
        while end_token>start_token:
            end_char=offsets[end_token][0] if end_token<len(offsets) else len(text)
            piece=text[start_char:end_char]
            length=len(tokenizer(piece,add_special_tokens=True,truncation=False)['input_ids'])
            if length<=max_tokens:break
            end_token-=1
        if end_token==start_token:raise ValueError('Cannot split one token into the stated model budget')
        chunks.append({'text':piece,'char_start':start_char,'char_end':end_char,'model_tokens':length})
        start_token=end_token;start_char=end_char
    assert ''.join(c['text'] for c in chunks)==text
    return chunks


def build_ledger(ingress,tokenizer):
    result=[];question_id=ingress['question_id'];clock(ingress['question_date'])
    for slot,session in enumerate(ingress['sessions']):
        clock(session['date'])
        for turn_index,turn in enumerate(session['turns']):
            text=turn['role']+': '+turn['content']
            for part,chunk in enumerate(split_text(text,tokenizer)):
                identity=json.dumps([question_id,slot,session['id'],turn_index,part],separators=(',',':'))
                result.append({**chunk,'id':hashlib.sha256(identity.encode()).hexdigest(),
                    'question_id':question_id,'session_slot':slot,'session_id':session['id'],'session_date':session['date'],
                    'turn_index':turn_index,'role':turn['role'],'part':part,'text_sha256':hashlib.sha256(chunk['text'].encode()).hexdigest()})
    return result


def select(ingress,chunks,scores,*,cutoff,limit):
    if len(chunks)!=len(scores):raise ValueError('One score is required per local candidate')
    latest=clock(ingress['question_date'])
    candidates=[]
    for chunk,score in zip(chunks,scores):
        if chunk['question_id']!=ingress['question_id']:raise ValueError('Cross-question candidate leakage')
        if not cutoff or clock(chunk['session_date'])<=latest:candidates.append({**chunk,'score':float(score)})
    return sorted(candidates,key=lambda c:(-c['score'],c['id']))[:limit]


def score_support(row,selected):
    # This is the only retrieval-diagnostic layer receiving official answer IDs.
    gold=set(row['answer_session_ids']);available=set(row['haystack_session_ids']);found={c['session_id'] for c in selected}&gold
    abstention=row['question_id'].endswith('_abs');mapped=gold<=available
    eligible=bool(gold) and mapped and not abstention
    return {'official_answer_session_ids':sorted(gold),'unmapped_answer_session_ids':sorted(gold-available),
        'qrel_coverage_complete':mapped,'support_sessions_returned':len(found),
        'support_session_recall':len(found)/len(gold) if eligible else None,
        'complete_support_sessions':bool(gold<=set(c['session_id'] for c in selected)) if eligible else None,
        'abstention_question':abstention,'empty_context':not selected,
        'diagnostic_note':'Session-level coverage does not establish that a selected chunk contains the answer. Retained _abs session IDs are excluded from positive support metrics.'}


def metrics(rows):
    answerable=[r for r in rows if r['support_session_recall'] is not None];absent=[r for r in rows if r['abstention_question']]
    return {'questions':len(rows),'mapped_answerable_questions':len(answerable),
        'mean_support_session_recall':sum(r['support_session_recall'] for r in answerable)/len(answerable) if answerable else None,
        'complete_support_sessions_rate':sum(r['complete_support_sessions'] for r in answerable)/len(answerable) if answerable else None,
        'abstention_questions':len(absent),'abstention_empty_context_rate':sum(r['empty_context'] for r in absent)/len(absent) if absent else None,
        'unmapped_questions':sum(not r['qrel_coverage_complete'] for r in rows)}


def snapshot_hashes(path=MODEL_PATH):
    return {file.relative_to(path).as_posix():sha256(file) for file in sorted(path.rglob('*')) if file.is_file()}


def main():
    p=add_provenance_argument(argparse.ArgumentParser());p.add_argument('--stage',choices=['preflight','run'],required=True)
    p.add_argument('--input',type=Path,default=ROOT/'.benchmark-data/longmemeval-s.json')
    p.add_argument('--output-dir',type=Path,default=ROOT/'docs/benchmarks-longmemeval')
    p.add_argument('--cache',type=Path,default=ROOT/'.benchmark-data/longmemeval-vectors.sqlite3')
    args=p.parse_args();run=BenchmarkRun(allow_dirty=args.allow_dirty)
    source_hash=sha256(args.input)
    if source_hash!=DATA_SHA:raise ValueError('Dataset differs from frozen LongMemEval-S source')
    rows=json.loads(args.input.read_text())
    if len(rows)!=500 or len({r['question_id'] for r in rows})!=500:raise ValueError('Expected 500 unique question scopes')
    from transformers import AutoTokenizer
    tokenizer=AutoTokenizer.from_pretrained(str(MODEL_PATH),local_files_only=True,use_fast=True)
    model_files=snapshot_hashes()
    model_identity=hashlib.sha256(json.dumps({'model':MODEL_NAME,'files':model_files,'tokens':MAX_TOKENS,'dtype':'float32','pooling':'SentenceTransformer default'},sort_keys=True).encode()).hexdigest()
    counts=Counter();unique_texts=set();records=[];context_lines=[];model=None;index=None;started=time.perf_counter()
    if args.stage=='run':
        from sentence_transformers import SentenceTransformer
        from chronoverse.vector_index import VectorIndex
        import torch
        if not torch.backends.mps.is_available():raise RuntimeError('Pinned protocol requires local MPS; CPU fallback is not silently substituted')
        model=SentenceTransformer(str(MODEL_PATH),device='mps',local_files_only=True);model.max_seq_length=MAX_TOKENS
        args.cache.parent.mkdir(parents=True,exist_ok=True);index=VectorIndex(args.cache)
    try:
        for number,row in enumerate(rows,1):
            ingress=public_ingress(row);chunks=build_ledger(ingress,tokenizer)
            counts['questions']+=1;counts['session_instances']+=len(ingress['sessions']);counts['turns']+=sum(len(s['turns']) for s in ingress['sessions'])
            counts['chunks']+=len(chunks);counts['model_tokens_with_specials']+=sum(c['model_tokens'] for c in chunks)
            counts['split_turns']+=sum(c['part']==1 for c in chunks)
            counts['future_session_instances']+=sum(clock(s['date'])>clock(ingress['question_date']) for s in ingress['sessions'])
            counts['duplicate_session_id_ledgers']+=len(ingress['sessions'])!=len({s['id'] for s in ingress['sessions']})
            query_tokens=len(tokenizer(ingress['question'],truncation=False)['input_ids']);counts['queries_exceeding_256_tokens']+=query_tokens>MAX_TOKENS
            unique_texts.update(c['text_sha256'] for c in chunks)
            if args.stage=='run':
                before=time.perf_counter()
                query_vector=model.encode([ingress['question']],batch_size=1,normalize_embeddings=False,show_progress_bar=False,convert_to_numpy=True)[0]
                encode=lambda texts:model.encode(texts,batch_size=32,normalize_embeddings=False,show_progress_bar=False,convert_to_numpy=True)
                scores=index.score(query_vector,[c['text'] for c in chunks],model_id=model_identity,dimensions=384,encode=encode)
                elapsed=time.perf_counter()-before
                methods={};contexts={}
                for name,cutoff in [('dense',False),('dense_session_date_cutoff',True)]:
                    selected=select(ingress,chunks,scores,cutoff=cutoff,limit=10)
                    methods[name]={'at5':score_support(row,selected[:5]),'at10':score_support(row,selected)}
                    contexts[name]=selected
                records.append({'question_id':row['question_id'],'question_type':row['question_type'],'methods':methods,
                                'local_candidate_chunks':len(chunks),'encoding_and_cosine_seconds':elapsed,'query_model_tokens':query_tokens})
                # Opaque IDs are linkage metadata, never answerer prompt content.
                safe_arms={name:[{'chunk_id':c['id'],'session_key':hashlib.sha256(json.dumps([ingress['question_id'],c['session_slot']]).encode()).hexdigest(),
                    'session_date':c['session_date'],'role':c['role'],'text':c['text']} for c in selected] for name,selected in contexts.items()}
                context_lines.append(json.dumps({'question_id':ingress['question_id'],'question':ingress['question'],
                    'question_date':ingress['question_date'],'arms':contexts,
                    'answerer_input':{'question':ingress['question'],'question_date':ingress['question_date'],'arms':safe_arms}},ensure_ascii=False))
            if number%25==0:print(json.dumps({'stage':args.stage,'questions':number,'chunks':counts['chunks'],'seconds':time.perf_counter()-started}),flush=True)
    finally:
        if index is not None:index.close()
    if sha256(args.input)!=source_hash:raise RuntimeError('Dataset changed during run')
    if snapshot_hashes()!=model_files:raise RuntimeError('Model artifacts changed during run; refusing mixed-model publication')
    report={'status':'preflight_only' if args.stage=='preflight' else 'complete','dataset':'LongMemEval-S cleaned','source_sha256':source_hash,
        'model':{'name':MODEL_NAME,'revision':MODEL_REVISION,'identity':model_identity,'files':model_files,'max_tokens':MAX_TOKENS,'device':'mps' if model else 'not loaded'},
        'inventory':dict(counts),'unique_exact_chunk_texts':len(unique_texts),'elapsed_seconds':time.perf_counter()-started,'paid_api_calls':0,
        'retrieval':'Question-ledger-only exact cosine over local MiniLM turn chunks; inclusive session-date cutoff is the sole second-arm difference.',
        'limitations':['Not Chronoverse lifecycle/receipt projection, not Graphiti, not answer accuracy. No delivery or source-recording labels are invented.',
            'Official answer_session_ids score coarse session coverage only, not answer-containing chunk recall.',
            'All30 _abs rows retain related session IDs; they are separated from positive support metrics.',
            'Model text contains only role and content. Answer labels, has_answer, question type, session IDs and question IDs are excluded from embeddings.',
            'Documents are losslessly split to <=256 model tokens; overlength questions use the documented model truncation and are counted.',
            'Exact-text vectors may be shared across ledgers; candidate membership, dates and rankings are never shared.',
            'Session timestamps are compared on the supplied timezone-unspecified calendar clock. No extra chronology is inferred.']}
    if args.stage=='run':
        report['per_query']=records;report['methods']={}
        for method in ('dense','dense_session_date_cutoff'):
            report['methods'][method]={cut:metrics([r['methods'][method][cut] for r in records]) for cut in ('at5','at10')}
            report['methods'][method]['by_ability']={ability:{cut:metrics([r['methods'][method][cut] for r in records if r['question_type']==ability]) for cut in ('at5','at10')} for ability in sorted({r['question_type'] for r in records})}
        receipt=run.write_bytes(args.output_dir/'contexts.jsonl',('\n'.join(context_lines)+'\n').encode())
        report['contexts_artifact']={'path':'contexts.jsonl','sha256':receipt['sha256'],'rows':len(context_lines),'provenance':receipt['provenance']}
    run.write_json(args.output_dir/('preflight.json' if args.stage=='preflight' else 'results.json'),report)
    print(json.dumps({'status':report['status'],'inventory':report['inventory'],'unique_chunks':len(unique_texts)}))


if __name__=='__main__':main()
