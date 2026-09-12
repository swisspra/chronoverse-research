"""Public FANToM presence-rule diagnostic; no answer fields enter receipt creation.

This is not passage retrieval evaluation or an official FANToM leaderboard run.
Scoring is opt-in and must follow a committed FANTOM-PROTOCOL.md.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time

from benchmarks.provenance import BenchmarkRun, add_provenance_argument

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'.benchmark-data/fantom-v1.json'
UPSTREAM_COMMIT='1cae6fa30f5ba04ca0fff5f5716b5ba7055e2e85'
ARCHIVE_SHA256='1d08dfa0ea474c7f83b9bc7e3a7b466eab25194043489dd618b4c5223e1253a4'
METHODS=('Global temporal','Scalar clock','Filter after projection','Ordinary SQL receipt filter','Delivery projection')
FIELDS=('infoAccessibilityQA_list','answerabilityQA_list','infoAccessibilityQAs_binary','answerabilityQAs_binary')
EXPECTED={'sets':870,'conversations':253,'parts':368,'factQA':870,'beliefQAs':1540,
          'infoAccessibilityQA_list':870,'answerabilityQA_list':870,
          'infoAccessibilityQAs_binary':3571,'answerabilityQAs_binary':3571}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def public_input(row):
    """Positive allowlist: never copy answer/gold/annotation fields to the adapter."""
    return {key:row[key] for key in ('set_id','part_id','conv_id','full_context','short_context','joining_speaker')}


def parse_turns(context):
    turns=[];unparsed=[]
    for line_number,line in enumerate(context.splitlines()):
        if not line.strip():continue
        match=re.match(r'^([^:\n]{1,80}):\s*(.*)$',line)
        if not match:
            unparsed.append(line_number)
            continue
        turns.append({'position':len(turns),'speaker':match[1].strip(),'text':match[2], 'source_line':line_number})
    return turns,unparsed


def build_presence(row):
    """Infer one public short-window absence episode; never infer semantic gold."""
    source=public_input(row)
    short,bad_short=parse_turns(source['short_context']);full,bad_full=parse_turns(source['full_context'])
    short_pairs=[(r['speaker'],r['text']) for r in short]
    full_pairs=[(r['speaker'],r['text']) for r in full]
    starts=[i for i in range(len(full)-len(short)+1) if full_pairs[i:i+len(short)]==short_pairs] if short else []
    own=[i for i,r in enumerate(short) if r['speaker']==source['joining_speaker']]
    warnings=[]
    if bad_short or bad_full:warnings.append('unparsed_context_lines')
    if len(starts)!=1:warnings.append('short_window_alignment_not_unique')
    if not own:warnings.append('joining_speaker_missing')
    gap=[];rule='unmapped';arrival=None
    if own and own[0]>0:
        arrival=own[0];gap=list(range(arrival));rule='first_turn_arrival'
    elif len(own)>1:
        arrival=own[1];gap=list(range(1,arrival));rule='initial_departure_then_next_own_turn'
    elif own:warnings.append('initial_turn_without_later_return')
    if not gap:warnings.append('empty_inferred_absence_window')
    offset=starts[0] if len(starts)==1 else None
    roster=sorted({t['speaker'] for t in full})
    short_roster=sorted({t['speaker'] for t in short})
    # Only the public selected short window supplies presence evidence. Speaking
    # elsewhere in full context does not establish attendance in this window.
    receipts=[]
    if not warnings:
        for recipient in short_roster:
            for position in range(len(short)):
                if recipient==source['joining_speaker'] and position in gap:continue
                receipts.append({'recipient_id':recipient,'turn_position':offset+position,'received_at':offset+position})
    return {'set_id':source['set_id'],'part_id':source['part_id'],'conv_id':source['conv_id'],
            'joining_speaker':source['joining_speaker'],'full_turns':full,'short_turns':short,
            'full_context_sha256':hashlib.sha256(source['full_context'].encode()).hexdigest(),
            'short_context_sha256':hashlib.sha256(source['short_context'].encode()).hexdigest(),
            'short_offset':offset,'full_roster':roster,'short_roster':short_roster,
            'absence_rule':rule,'arrival_short_position':arrival,'gap_short_positions':gap,
            'target_turn_positions':[offset+i for i in gap] if offset is not None else [],
            'receipts':receipts,'warnings':warnings,'mapped':not warnings}


def inventory(rows):
    counts={'sets':len(rows),'conversations':len({r['conv_id'] for r in rows}),'parts':len({r['part_id'] for r in rows})}
    for field in ('factQA','beliefQAs',*FIELDS):
        counts[field]=sum(len(r[field]) if isinstance(r[field],list) else int(r[field] is not None) for r in rows)
    assert counts==EXPECTED,(counts,EXPECTED)
    contexts=[build_presence(r) for r in rows]
    return {'counts':counts,'presence_mapping':{'mapped_sets':sum(c['mapped'] for c in contexts),
        'unmapped_sets':sum(not c['mapped'] for c in contexts),'rules':dict(Counter(c['absence_rule'] for c in contexts)),
        'warning_counts':dict(Counter(w for c in contexts for w in c['warnings']))},
        'not_scored_types':{'factQA':{'count':counts['factQA'],'reason':'Free-form fact answer requires an answerer; no official passage qrels.'},
                           'beliefQAs':{'count':counts['beliefQAs'],'reason':'Belief reasoning and generated multiple-choice prompts require an answerer; presence is not belief.'}}}


def received_positions(context,recipient,method,input_type):
    if method not in METHODS:raise ValueError(method)
    start=context['short_offset'] if input_type=='short' else 0
    cutoff=(start+len(context['short_turns'])-1) if input_type=='short' else len(context['full_turns'])-1
    if method in METHODS[:2]:
        roster=context['short_roster'] if input_type=='short' else context['full_roster']
        # One common clock at the end of the selected context cannot encode a
        # recipient's attendance gap. Scalar therefore equals the global arm.
        return list(range(start,cutoff+1)) if recipient in roster else []
    if method=='Ordinary SQL receipt filter':
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE receipts(recipient TEXT, turn_position INTEGER, received_at INTEGER)')
            db.executemany('INSERT INTO receipts VALUES (?,?,?)',[(r['recipient_id'],r['turn_position'],r['received_at']) for r in context['receipts']])
            return [r[0] for r in db.execute('SELECT DISTINCT turn_position FROM receipts WHERE recipient=? AND received_at<=? ORDER BY turn_position',(recipient,cutoff))]
    visible={r['turn_position'] for r in context['receipts'] if r['recipient_id']==recipient and r['received_at']<=cutoff}
    if method=='Filter after projection':
        global_rows=range(cutoff+1)
        return [position for position in global_rows if position in visible]
    return sorted(visible)


def predict(context,method,input_type):
    if not context['mapped']:return {'prediction':None,'reason':context['warnings'],'received_turn_positions':{}}
    roster=context['short_roster'] if input_type=='short' else context['full_roster']
    received={person:received_positions(context,person,method,input_type) for person in roster}
    target=set(context['target_turn_positions'])
    predicted=[person for person in roster if target<=set(received[person])]
    return {'prediction':predicted,'received_turn_positions':received,
            'reason':'All inferred absence-window turns delivered under this method; no semantic fact matching.'}


def evaluation_questions(row,input_type):
    """Evaluation-side only. Gold cannot flow into build_presence or predict."""
    for field in FIELDS:
        entries=row[field] if isinstance(row[field],list) else [row[field]]
        for index,qa in enumerate(entries):
            if qa is None:continue
            binary=field.endswith('_binary')
            target=re.fullmatch(r'Does (.+?) know(?: this information| the precise correct answer to this question)\?',qa['question']) if binary else None
            yield {'id':f"{row['set_id']}:{input_type}:{field}:{index}",'set_id':row['set_id'],
                   'family':field,'input_type':input_type,'question':qa['question'],
                   'fact_question':row['factQA']['question'],'target_recipient':target[1] if target else None,
                   'gold_answer':deepcopy(qa['correct_answer']),'wrong_answer':deepcopy(qa.get('wrong_answer',[])),
                   'eligible':not(binary and input_type=='short' and qa['correct_answer']=='no:long'),
                   'exclusion_reason':'Official short-context no:long exclusion' if binary and input_type=='short' and qa['correct_answer']=='no:long' else None,
                   'annotation_scenario':qa.get('missed_info_accessibility')}


def score_question(question,predicted):
    if predicted is None:return {'predicted_answer':None,'correct':False,'mapped':False}
    if question['family'].endswith('_binary'):
        target=question['target_recipient']
        if target is None:return {'predicted_answer':None,'correct':False,'mapped':False}
        answer='yes' if target in predicted else 'no'
        return {'predicted_answer':answer,'correct':answer==question['gold_answer'].split(':')[0],'mapped':True}
    # Reproduce official list membership criterion on our deterministic name list.
    response=', '.join(predicted).lower()
    correct=all(name.lower() in response for name in question['gold_answer']) and not any(name.lower() in response for name in question['wrong_answer'])
    return {'predicted_answer':predicted,'correct':correct,'mapped':True}


def weighted_f1(rows):
    total=len(rows)
    if not total:return None
    answer=0.
    for label in ('yes','no'):
        tp=sum(r['gold_answer'].split(':')[0]==label and r['predicted_answer']==label for r in rows)
        fp=sum(r['gold_answer'].split(':')[0]!=label and r['predicted_answer']==label for r in rows)
        fn=sum(r['gold_answer'].split(':')[0]==label and r['predicted_answer']!=label for r in rows)
        support=sum(r['gold_answer'].split(':')[0]==label for r in rows)
        answer+=support*(2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.)
    return answer/total


def summarize(rows):
    groups=defaultdict(list)
    for row in rows.values():groups[(row['input_type'],row['family'])].append(row)
    output={}
    for (input_type,family),all_rows in groups.items():
        eligible=[r for r in all_rows if r['eligible']]
        mapped=[r for r in eligible if r['mapped']]
        output[f'{input_type}:{family}']={'raw_queries':len(all_rows),'official_eligible_queries':len(eligible),
            'excluded_no_long':len(all_rows)-len(eligible),'mapped_queries':len(mapped),
            'coverage':len(mapped)/len(eligible) if eligible else None,
            'accuracy_all_eligible_unmapped_wrong':sum(r['correct'] for r in eligible)/len(eligible) if eligible else None,
            'accuracy_mapped_only':sum(r['correct'] for r in mapped)/len(mapped) if mapped else None,
            'weighted_f1_all_eligible':weighted_f1(eligible) if family.endswith('_binary') else None}
    return output


def run(rows):
    # All ingress projections and predictions are completed before gold extraction.
    contexts={row['set_id']:build_presence(row) for row in rows}
    outputs={m:{} for m in METHODS};traces={m:{} for m in METHODS}
    for context_type in ('short','full'):
        for sid,context in contexts.items():
            for method in METHODS:
                start=time.perf_counter();prediction=predict(context,method,context_type)
                traces[method][f'{sid}:{context_type}']={**prediction,'seconds':time.perf_counter()-start}
    for row in rows:
        for context_type in ('short','full'):
            for question in evaluation_questions(row,context_type):
                for method in METHODS:
                    trace_id=f"{row['set_id']}:{context_type}"
                    output=score_question(question,traces[method][trace_id]['prediction'])
                    outputs[method][question['id']]={**question,**output,'trace_id':trace_id}
    return {'methods':{m:{'metrics':summarize(outputs[m]),'per_query':outputs[m],'presence_traces':traces[m]} for m in METHODS},
            'contexts':contexts}


def main():
    parser=add_provenance_argument(argparse.ArgumentParser())
    parser.add_argument('--input',type=Path,default=DATA)
    parser.add_argument('--score',action='store_true',help='Score only after protocol/code are committed; default prints metadata inventory only.')
    parser.add_argument('--output',type=Path,default=ROOT/'docs/benchmarks-next/fantom-results.json')
    args=parser.parse_args()
    rows=json.loads(args.input.read_text())
    info=inventory(rows)
    if not args.score:
        print(json.dumps(info,indent=2));return
    context=BenchmarkRun(allow_dirty=args.allow_dirty)
    archive=ROOT/'.benchmark-data/fantom.tar.gz'
    assert sha(archive)==ARCHIVE_SHA256
    result={'status':'complete','experiment':'FANToM presence-rule adapter diagnostic, not official leaderboard or passage retrieval evaluation',
            'inventory':info,'upstream_commit':UPSTREAM_COMMIT,'source_sha256':{
                'dataset_json':sha(args.input),'official_archive':sha(archive),
                'official_evaluator':sha(ROOT/'.benchmark-data/fantom-eval_fantom.py'),
                'adapter':sha(Path(__file__)),'protocol':sha(ROOT/'docs/benchmarks-next/FANTOM-PROTOCOL.md')},
            'model':None,'paid_api_calls':0,**run(rows)}
    context.write_json(args.output,result)
    print(json.dumps({'output':str(args.output),'status':'complete'}))


if __name__=='__main__':main()
