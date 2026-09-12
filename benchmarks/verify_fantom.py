"""Read-only FANToM saved-prediction audit against original public labels.

No adapter or presence-rule algorithm is imported or rerun. This is neither
passage-retrieval evaluation, belief reasoning, nor an official leaderboard run.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
FAMILIES=('infoAccessibilityQA_list','answerabilityQA_list','infoAccessibilityQAs_binary','answerabilityQAs_binary')


def digest(value):return hashlib.sha256(value).hexdigest()


def compare_metrics(actual,expected,label):
    assert set(actual)==set(expected),label+': metric fields'
    for key,value in expected.items():
        if isinstance(value,float):assert math.isclose(actual[key],value,rel_tol=1e-12,abs_tol=1e-12),label+': '+key
        else:assert actual[key]==value,label+': '+key


def weighted_f1(rows):
    total=len(rows);score=0.
    for label in ('yes','no'):
        support=sum(gold==label for gold,predicted in rows)
        tp=sum(gold==label and predicted==label for gold,predicted in rows)
        fp=sum(gold!=label and predicted==label for gold,predicted in rows)
        fn=support-tp
        score+=(support/total)*(2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.)
    return score


def verify(directory,data_dir):
    directory=Path(directory);data_dir=Path(data_dir)
    summary=json.loads((directory/'fantom-result-summary.json').read_text());storage=summary['raw_artifact']
    compressed=(directory/storage['file']).read_bytes();raw=gzip.decompress(compressed)
    assert digest(compressed)==storage['compressed_sha256'],'FANToM compressed hash'
    assert digest(raw)==storage['uncompressed_sha256'],'FANToM original hash'
    assert len(compressed)==storage['compressed_bytes'] and len(raw)==storage['uncompressed_bytes'],'FANToM bytes'
    result=json.loads(raw)
    for key in ('status','experiment','inventory','upstream_commit','source_sha256','model','paid_api_calls','provenance'):
        assert result[key]==summary[key],f'FANToM summary {key}'
    assert result['status']=='complete' and result['model'] is None and result['paid_api_calls']==0
    paths={'dataset_json':'fantom-v1.json','official_archive':'fantom.tar.gz','official_evaluator':'fantom-eval_fantom.py'}
    for key,name in paths.items():assert digest((data_dir/name).read_bytes())==result['source_sha256'][key],f'FANToM public source {key}'
    # Hash only, without executing or importing the adapter being audited.
    for key,path in [('adapter','benchmarks/fantom_adapter.py'),('protocol','docs/benchmarks-next/FANTOM-PROTOCOL.md')]:
        recorded=subprocess.check_output(['git','show',result['provenance']['git_commit']+':'+path],cwd=ROOT)
        assert digest(recorded)==result['source_sha256'][key],f'FANToM archived {key}'
    public=json.loads((data_dir/'fantom-v1.json').read_text());sets={row['set_id']:row for row in public}
    assert len(sets)==len(public) and set(result['contexts'])==set(sets),'FANToM source sets'
    counts={'sets':len(public),'conversations':len({row['conv_id'] for row in public}),'parts':len({row['part_id'] for row in public}),
            'factQA':sum(row.get('factQA') is not None for row in public),'beliefQAs':sum(len(row['beliefQAs']) for row in public)}
    counts.update({family:sum(len(row[family]) if isinstance(row[family],list) else int(row[family] is not None) for row in public) for family in FAMILIES})
    assert counts==result['inventory']['counts'],'FANToM inventory counts'
    contexts=list(result['contexts'].values());mapping=result['inventory']['presence_mapping']
    assert mapping['mapped_sets']==sum(c['mapped'] for c in contexts) and mapping['unmapped_sets']==sum(not c['mapped'] for c in contexts),'FANToM recorded mapping counts'
    assert mapping['rules']==dict(Counter(c['absence_rule'] for c in contexts)),'FANToM recorded rule counts'
    assert mapping['warning_counts']==dict(Counter(w for c in contexts for w in c['warnings'])),'FANToM recorded warning counts'
    expected={}
    for source in public:
        context=result['contexts'][source['set_id']]
        assert context['full_context_sha256']==digest(source['full_context'].encode()),'FANToM full context'
        assert context['short_context_sha256']==digest(source['short_context'].encode()),'FANToM short context'
        for input_type in ('short','full'):
            for family in FAMILIES:
                family_rows=source[family] if isinstance(source[family],list) else [source[family]]
                for index,label in enumerate(family_rows):
                    qid=f"{source['set_id']}:{input_type}:{family}:{index}"
                    expected[qid]=(source,label,family,input_type)
    verified=0
    for method,data in result['methods'].items():
        assert set(data['per_query'])==set(expected),f'{method}: public query coverage'
        assert summary['methods'][method]['metrics']==data['metrics'],f'{method}: summary metrics'
        grouped=defaultdict(list)
        for qid,row in data['per_query'].items():
            source,label,family,input_type=expected[qid]
            assert row['id']==qid and row['set_id']==source['set_id'] and row['family']==family and row['input_type']==input_type,f'{method}: query identity'
            assert row['question']==label['question'] and row['fact_question']==source['factQA']['question'],f'{method}: public question'
            assert row['gold_answer']==label['correct_answer'] and row['wrong_answer']==label.get('wrong_answer',[]),f'{method}/{qid}: public gold'
            eligible=not(input_type=='short' and family.endswith('_binary') and label['correct_answer']=='no:long')
            assert row['eligible']==eligible,f'{method}/{qid}: official no:long exclusion'
            mapped=result['contexts'][source['set_id']]['mapped']
            assert row['mapped']==mapped,f'{method}/{qid}: recorded mapping coverage'
            predicted=row['predicted_answer']
            if family.endswith('_binary'):
                gold=label['correct_answer'].split(':')[0]
                assert predicted in ('yes','no',None),f'{method}/{qid}: binary prediction'
                correct=mapped and predicted==gold
            else:
                assert predicted is None or isinstance(predicted,list),f'{method}/{qid}: list prediction'
                response=', '.join(predicted or []).lower()
                correct=mapped and all(name.lower() in response for name in label['correct_answer']) and not any(name.lower() in response for name in label['wrong_answer'])
                gold=None
            assert row['correct']==correct,f'{method}/{qid}: correctness against public label'
            grouped[input_type+':'+family].append({'eligible':eligible,'mapped':mapped,'correct':correct,'gold':gold,'predicted':predicted})
            verified+=1
        for group,rows in grouped.items():
            eligible=[row for row in rows if row['eligible']];mapped=[row for row in eligible if row['mapped']]
            expected_metrics={'raw_queries':len(rows),'official_eligible_queries':len(eligible),'excluded_no_long':len(rows)-len(eligible),
                'mapped_queries':len(mapped),'coverage':len(mapped)/len(eligible),
                'accuracy_all_eligible_unmapped_wrong':sum(row['correct'] for row in eligible)/len(eligible),
                'accuracy_mapped_only':sum(row['correct'] for row in mapped)/len(mapped),
                'weighted_f1_all_eligible':weighted_f1([(row['gold'],row['predicted']) for row in eligible]) if group.endswith('_binary') else None}
            compare_metrics(data['metrics'][group],expected_metrics,method+':'+group)
    return {'status':'verified','sets':len(public),'methods':len(result['methods']),'verified_predictions':verified,
            'source_result_sha256':digest(raw),'scope':'Saved binary/list predictions checked against public FANToM labels, official short no:long exclusion, list containment and weighted F1. Mapping algorithm not rerun; no retrieval, belief, or leaderboard claim.'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--input-dir',type=Path,default=ROOT/'docs/benchmarks-next');p.add_argument('--data-dir',type=Path,default=ROOT/'.benchmark-data')
    args=p.parse_args();print(json.dumps(verify(args.input_dir,args.data_dir),indent=2))


if __name__=='__main__':main()
