"""Fixed paired-query answer statistics; unsuccessful attempts stay visible."""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import statistics
import numpy as np
from benchmarks.answer_experiment import PROMPT,score_answer
from benchmarks.provenance import BenchmarkRun,add_provenance_argument,sha256

SEED=20260913
METRICS=('closed_form','support_recovery','end_to_end','correct_abstention','false_abstention')
CONTRASTS=('A','B','C','D')


def mean(values):return statistics.mean(values) if values else None


def validate_binding(raw,rows,result,prompt_bytes,captured=None):
    """Require an explicit dispatch identity, including for partial checkpoints."""
    binding=result if result.get('manifest_sha256') is not None else captured
    if not binding:raise ValueError('Missing captured manifest/prompt hashes; checkpoint association cannot be inferred.')
    manifest_hash=hashlib.sha256(raw).hexdigest();prompt_hash=hashlib.sha256(prompt_bytes).hexdigest()
    if binding.get('manifest_sha256')!=manifest_hash:raise ValueError('Result/captured export is bound to a different raw manifest hash.')
    if binding.get('prompt_sha256')!=prompt_hash or any(r.get('prompt_sha256')!=prompt_hash for r in rows):raise ValueError('Result, manifest and prompt hashes are inconsistent.')
    return {'manifest_sha256':manifest_hash,'prompt_sha256':prompt_hash,
        'source':'Final result hashes' if binding is result else 'Explicit captured-input hash export; not inferred from checkpoint IDs'}


def resource_summary(records,completed,answered):
    def latency(values):
        samples=[r['seconds'] for r in values if isinstance(r.get('seconds'),(int,float)) and np.isfinite(r['seconds']) and r['seconds']>=0]
        return {'samples':len(samples),'missing':len(values)-len(samples),'mean_seconds':mean(samples),
            'p50_seconds':float(np.percentile(samples,50)) if samples else None,'p95_seconds':float(np.percentile(samples,95)) if samples else None}
    observed={};missing={}
    for key in ('prompt_tokens','completion_tokens','total_tokens'):
        values=[r.get('usage',{}).get(key) for r in records if isinstance(r.get('usage'),dict)]
        values=[v for v in values if isinstance(v,(int,float)) and np.isfinite(v) and v>=0]
        observed[key]=sum(values) if values else None;missing[key]=len(records)-len(values)
    answered_tokens=[r['usage']['total_tokens'] for r in answered if isinstance(r.get('usage'),dict) and isinstance(r['usage'].get('total_tokens'),(int,float))]
    return {'recorded_attempts':len(records),'valid_completed_attempts':len(completed),'nonabstained_completed_count':len(answered),
        'observed_tokens':observed,'missing_usage_counts':missing,
        'attempts_without_usage':sum(not isinstance(r.get('usage'),dict) or not r['usage'] for r in records),
        'latency':{'recorded_attempts':latency(records),'valid_completed':latency(completed)},
        'tokens_per_answered_attempt':observed['total_tokens']/len(answered) if answered and observed['total_tokens'] is not None else None,
        'tokens_per_answered_attempt_definition':'All observed arm total_tokens / valid nonabstained completions; includes abstention and failed-attempt overhead; partial when usage is missing.',
        'answered_attempt_mean_reported_tokens':mean(answered_tokens),'answered_attempts_with_reported_tokens':len(answered_tokens),
        'usd':None,'pricing':'Proxy rates unknown; observed tokens are not a USD bill.'}


def paired(differences,families,*,bootstrap=10000,permutations=20000):
    if not differences:return None
    d=np.array(differences,dtype=float);rng=np.random.default_rng(SEED)
    boot=np.zeros(bootstrap)
    for family in sorted(set(families)):
        indices=np.array([i for i,f in enumerate(families) if f==family])
        boot+=d[rng.choice(indices,size=(bootstrap,len(indices)),replace=True)].sum(axis=1)/len(d)
    observed=float(d.mean());flipped=(rng.choice((-1,1),size=(permutations,len(d)))*d).mean(axis=1)
    return {'query_pairs':len(d),'difference_E_minus_other':observed,
        'ci95':np.quantile(boot,[.025,.975]).tolist(),'bonferroni_ci98_75':np.quantile(boot,[.00625,.99375]).tolist(),
        'p_raw':float((1+np.count_nonzero(np.abs(flipped)>=abs(observed)-1e-12))/(permutations+1)),
        'bootstrap_replicates':bootstrap,'sign_flip_draws':permutations,'seed':SEED}


def holm(comparisons):
    ordered=sorted([(key,value['p_raw']) for key,value in comparisons.items() if value is not None and 'p_raw' in value],key=lambda pair:pair[1]);running=0
    for i,(key,p) in enumerate(ordered):
        running=max(running,min(1,(4-i)*p));comparisons[key]['p_holm']=running


def summarize(rows,records,expected_model,*,bootstrap=10000,permutations=20000):
    by={(r['query_id'],r['arm']):r for r in rows}
    if len(by)!=len(rows):raise ValueError('Duplicate manifest query/arm.')
    queries=sorted({r['query_id'] for r in rows});arms=sorted({r['arm'] for r in rows})
    if arms!=list('ABCDE') or any((q,a) not in by for q in queries for a in arms):raise ValueError('Fixed statistics require all five arms.')
    shared=('question','recipient_id','valid_at','known_at','received_by','expected_answers','gold_support_ids',
        'support_equivalence_groups','visible_ids','stale_ids','answerable','family','event_only')
    for q in queries:
        if any(by[q,a].get(key)!=by[q,'A'].get(key) for a in arms for key in shared):raise ValueError('Shared scoring/query metadata differs across arms.')
    indexed={}
    for record in records.values():
        key=(record['query_id'],record['arm'],record['repeat'])
        if key in indexed or key[:2] not in by or key[2] not in (0,1,2):raise ValueError('Unexpected/duplicate recorded dispatch slot.')
        indexed[key]=record
    per_query={};counts={a:Counter() for a in arms};usage=Counter();actual=Counter()
    resources={a:{'records':[],'completed':[],'answered':[]} for a in arms}
    for q in queries:
        per_query[q]={'family':by[q,'A']['family'],'arms':{}}
        for arm in arms:
            row=by[q,arm];repeats=[]
            for repeat in range(3):
                record=indexed.get((q,arm,repeat),{});status=record.get('status','missing');counts[arm][status]+=1
                valid=status=='complete' and record.get('finish_reason')=='stop' and record.get('returned_model')==expected_model and not any(record.get(k) for k in ('model_guard_failure','budget_breach'))
                if record:actual[str(record.get('returned_model','unknown'))]+=1
                if record.get('usage'):
                    for key in ('prompt_tokens','completion_tokens','total_tokens'):
                        if key in record['usage']:usage[key]+=record['usage'][key]
                        else:usage['attempts_without_'+key]+=1
                else:usage['attempts_without_usage']+=1
                score=score_answer(record['raw_answer'],row) if valid else None
                if record:resources[arm]['records'].append(record)
                if valid:
                    resources[arm]['completed'].append(record)
                    if not score['abstained']:resources[arm]['answered'].append(record)
                answerable=row['answerable'];clean=valid and not any(score[k] for k in ('citation_leak_ids','stale_citation_ids','unknown_context_citation_ids'))
                values={'valid_completion':int(valid),'closed_form':int(valid and score['answer_closed_form_match']),
                    'support_recovery':int(valid and score['equivalent_support_complete']) if answerable else None,
                    'end_to_end':int(clean and score['answer_closed_form_match'] and score['equivalent_support_complete']) if answerable else None,
                    'correct_abstention':int(valid and score['correct_abstention']) if not answerable else None,
                    'false_abstention':int(score['false_abstention']) if valid and answerable else None,
                    'strict_support_complete':int(score['support_complete']) if valid and answerable else None,
                    'citation_leak':int(bool(score['citation_leak_ids'])) if valid else None,
                    'stale_citation':int(bool(score['stale_citation_ids'])) if valid else None,
                    'unknown_context_citation':int(bool(score['unknown_context_citation_ids'])) if valid else None}
                repeats.append({'repeat':repeat,'status':status,'metrics':values,'seconds':record.get('seconds')})
            per_query[q]['arms'][arm]=repeats
    metrics=tuple(next(iter(per_query.values()))['arms']['A'][0]['metrics']);summaries={};families={}
    def aggregate(qids,arm):
        result={}
        for metric in metrics:
            values=[r['metrics'][metric] for q in qids for r in per_query[q]['arms'][arm] if r['metrics'][metric] is not None]
            result[metric]={'value':mean(values),'denominator':len(values)}
        result['failed_fraction']=1-result['valid_completion']['value']
        return result
    for arm in arms:
        summaries[arm]={'metrics':aggregate(queries,arm),'statuses':dict(counts[arm]),'repeat_variation':{},'resources':resource_summary(**resources[arm])}
        for metric in METRICS:
            metric_queries=[q for q in queries if (by[q,arm]['answerable'] if metric in ('support_recovery','end_to_end','false_abstention') else not by[q,arm]['answerable'] if metric=='correct_abstention' else True)]
            rates=[mean([per_query[q]['arms'][arm][r]['metrics'][metric] for q in metric_queries if per_query[q]['arms'][arm][r]['metrics'][metric] is not None]) for r in range(3)]
            summaries[arm]['repeat_variation'][metric]={'rates':rates,'sample_variance':statistics.variance(rates) if all(r is not None for r in rates) else None,
                'range':max(rates)-min(rates) if all(r is not None for r in rates) else None,
                'queries_with_changed_outcome':sum(len({r['metrics'][metric] for r in per_query[q]['arms'][arm] if r['metrics'][metric] is not None})>1 for q in metric_queries),
                'queries_with_unknown_repeat':sum(any(r['metrics'][metric] is None for r in per_query[q]['arms'][arm]) for q in metric_queries)}
    for family in sorted({per_query[q]['family'] for q in queries}):
        subset=[q for q in queries if per_query[q]['family']==family];families[family]={'queries':len(subset),'arms':{a:aggregate(subset,a) for a in arms}}
    contrasts={}
    for metric in METRICS:
        comparisons={}
        for arm in CONTRASTS:
            eligible=[q for q in queries if (by[q,'E']['answerable'] if metric in ('support_recovery','end_to_end','false_abstention') else not by[q,'E']['answerable'] if metric=='correct_abstention' else True)]
            chosen=[q for q in eligible if all(r['metrics'][metric] is not None for a in ('E',arm) for r in per_query[q]['arms'][a])]
            differences=[mean([r['metrics'][metric] for r in per_query[q]['arms']['E']])-mean([r['metrics'][metric] for r in per_query[q]['arms'][arm]]) for q in chosen]
            if metric=='false_abstention' and len(chosen)<30:
                comparison={'query_pairs':len(chosen),'difference_E_minus_other':mean(differences),'inference':'Descriptive only: fewer than30 complete query pairs.'}
            else:comparison=paired(differences,[per_query[q]['family'] for q in chosen],bootstrap=bootstrap,permutations=permutations)
            if comparison is not None:
                comparison.update(eligible_query_count=len(eligible),excluded_query_count=len(eligible)-len(chosen))
                if metric=='false_abstention':comparison['selection_caveat']='Complete-pair selection may be biased; no confirmatory interpretation.'
            comparisons['E-'+arm]=comparison
        holm(comparisons);contrasts[metric]=comparisons
    return {'planned_queries':len(queries),'planned_requests':len(rows)*3,'recorded_requests':len(records),'expected_response_model':expected_model,
        'actual_response_models':dict(actual),'arms':summaries,'families':families,'paired_contrasts':contrasts,'usage':dict(usage),'per_query':per_query,
        'limitations':['Literal string matching is not semantic exact match.','Invalid attempts fail accuracy/recovery; citation audits are unknown and use completed-only denominators.',
            'Query is the paired unit; three repeats are not independent queries.','Four E contrasts form one multiplicity family per metric, not study-wide across metrics.',
            'Standalone passages can omit inherited parent validity metadata when the parent chunk is absent; common candidate inventory is not identical information coverage. Full-history B is the strong history control.',
            'Synthetic fixed families and sign-flip symmetry limit inferential interpretation.']}


def main():
    parser=add_provenance_argument(argparse.ArgumentParser());parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--results',type=Path,required=True);parser.add_argument('--expected-response-model',required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--prompt',type=Path,default=PROMPT)
    parser.add_argument('--captured-input-hashes',type=Path,help='Explicit dispatch-captured manifest_sha256/prompt_sha256 export, required for a checkpoint lacking final result hashes.')
    args=parser.parse_args();run=BenchmarkRun(allow_dirty=args.allow_dirty);inputs={p:sha256(p) for p in (args.manifest,args.results,args.prompt)}
    if args.captured_input_hashes:inputs[args.captured_input_hashes]=sha256(args.captured_input_hashes)
    raw=args.manifest.read_bytes();raw=gzip.decompress(raw) if args.manifest.suffix=='.gz' else raw
    rows=[json.loads(line) for line in raw.decode().splitlines() if line.strip()];result=json.loads(args.results.read_text())
    binding=validate_binding(raw,rows,result,args.prompt.read_bytes(),json.loads(args.captured_input_hashes.read_text()) if args.captured_input_hashes else None)
    summary=summarize(rows,result['requests'],args.expected_response_model)
    if any(sha256(p)!=value for p,value in inputs.items()):raise RuntimeError('Statistics input changed during aggregation.')
    run.write_json(args.output,{'status':'complete' if summary['recorded_requests']==summary['planned_requests'] else 'partial attempts retained',
        'manifest_file_sha256':inputs[args.manifest],'result_file_sha256':inputs[args.results],
        'manifest_binding':binding,'captured_hash_export_sha256':inputs.get(args.captured_input_hashes),**summary})


if __name__=='__main__':main()
