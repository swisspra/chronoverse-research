"""Read-only LongMemEval-S inventory and gold-free ingestion budget preflight."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from benchmarks.provenance import BenchmarkRun

ROOT=Path(__file__).resolve().parents[1]
REVISION='98d7416c24c778c2fee6e6f3006e7a073259d48f'


def public_history(row):
    return {'question_id':row['question_id'],'question':row['question'],'question_date':row['question_date'],
            'sessions':[{'id':sid,'date':date,'turns':[{'role':turn['role'],'content':turn['content']} for turn in turns]}
                for sid,date,turns in zip(row['haystack_session_ids'],row['haystack_dates'],row['haystack_sessions'],strict=True)]}


def inventory(rows):
    data=[public_history(row) for row in rows]
    sessions=[session for row in data for session in row['sessions']]
    texts=['\n'.join(turn['role']+': '+turn['content'] for turn in session['turns']) for session in sessions]
    unique={hashlib.sha256(text.encode()).hexdigest():text for text in texts}
    return {'questions':len(rows),'question_types':dict(Counter(row['question_type'] for row in rows)),
            'abstention_questions':sum(row['question_id'].endswith('_abs') for row in rows),
            'session_ingestions_without_cross_question_state_sharing':len(sessions),
            'unique_session_texts_for_embedding_cache_only':len(unique),'turns':sum(len(session['turns']) for session in sessions),
            'history_utf8_bytes':sum(len(text.encode()) for text in texts),
            'distinct_history_utf8_bytes':sum(len(text.encode()) for text in unique.values()),
            'native_graphiti_ingestion_note':'Actual native episode ingestion can call extraction, deduplication and invalidation LLMs more than once per episode. Session count is not a complete request/token estimate.',
            'native_graphiti_evaluation':'not run; no surrogate is reported as Graphiti',
            'answer_track':'not run; official answer labels and has_answer flags are excluded from ingress',
            'clock_limit':'Session dates do not supply independently annotated recipient-delivery times or source recording delays. Do not invent a third-clock advantage from these dates.'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--allow-dirty',action='store_true');args=p.parse_args()
    run=BenchmarkRun(allow_dirty=args.allow_dirty,sources=[Path(__file__),ROOT/'benchmarks/provenance.py'])
    path=ROOT/'.benchmark-data/longmemeval-s.json';rows=json.loads(path.read_text());assert len(rows)==500
    result={'status':'preflight_only','dataset':'LongMemEval-S cleaned','revision':REVISION,'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'license':'MIT per pinned Hugging Face dataset card','source_url':f'https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/tree/{REVISION}',
        'inventory':inventory(rows),'paid_api_calls':0,'next_gate':'Freeze native ingestion configuration and estimate measured per-episode token use after chat routing is confirmed.'}
    run.write_json(ROOT/'docs/benchmarks-next/longmemeval-preflight.json',result)
    print(json.dumps(result['inventory']))

if __name__=='__main__':main()
