"""Separate paired analysis of an immutable delivery-v3 result bundle."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from benchmarks.delivery_v3 import CORRECTION_FAMILIES, ITEM_LABEL
from benchmarks.provenance import BenchmarkRun, add_provenance_argument, sha256
from benchmarks.statistics import paired_comparison, holm

BASELINES=('Global temporal','Scalar clock','Filter after projection')


def _complete(row):
    if not row['gold_support']:
        raise ValueError('Complete-support comparison requires answerable cases')
    return float(not row['missing_support'])


def comparisons(pairs,methods,*,samples,cluster_field):
    output={}
    for name,(left,right,queries) in pairs.items():
        output[name]={**paired_comparison([_complete(methods[left]['per_query'][q['id']]) for q in queries],
            [_complete(methods[right]['per_query'][q['id']]) for q in queries],
            clusters=[q.get(cluster_field,q['id']) for q in queries],samples=samples,family_size=len(pairs)),
            'left':left,'right':right,'query_ids':[q['id'] for q in queries],
            'metric':'complete_support_rate','cluster_field':cluster_field}
    for row,adjusted in zip(output.values(),holm([r['p_value'] for r in output.values()])):
        row['holm_p_value']=adjusted
    return output


def analyze(result,*,samples=10000):
    if result['status']!='complete':raise ValueError('Analysis requires a complete result bundle')
    methods=result['methods']
    for name,method in methods.items():
        stable=method['stability']
        if stable['matching_repeated_signatures']!=stable['comparisons']:
            raise ValueError(f'Refusing unstable method {name}')
    test=[q for q in result['query_manifest'] if q.get('split')=='test']
    primary=[q for q in test if q.get('family') in CORRECTION_FAMILIES and q.get('kind')!='event']
    if not primary:raise ValueError('No answerable TEST correction-family claims')
    groups={'pooled_primary':primary}
    groups.update({family:[q for q in primary if q['family']==family] for family in sorted(CORRECTION_FAMILIES) if any(q['family']==family for q in primary)})
    pairs={f'{group}: delivery minus {baseline}':('Delivery projection',baseline,queries)
           for group,queries in groups.items() for baseline in BASELINES}
    extension_groups={'event_notice_support':[q for q in test if q.get('kind')=='event'],
                      'standalone_evidence_support':[q for q in test if q.get('kind')=='evidence']}
    extension_pairs={name:(ITEM_LABEL,'Delivery projection',queries) for name,queries in extension_groups.items() if queries}
    return {'status':'complete','source_run_commit':result.get('provenance',{}).get('git_commit'),
            'fixture_sha256':result['fixture_sha256'],'source_embedding_mode':result.get('embedding_mode'),
            'source_model':result.get('model'),'primary_query_ids':[q['id'] for q in primary],
            'primary_families':sorted(CORRECTION_FAMILIES),'comparison_family_policy':
                'All pooled-primary and individual-primary-family contrasts against three predeclared baselines form one Holm/Bonferroni family. Item-extension notice/evidence contrasts form a separate exploratory capability family.',
            'primary_comparisons':comparisons(pairs,methods,samples=samples,cluster_field='cluster_id'),
            'scenario_template_sensitivity':comparisons(pairs,methods,samples=samples,cluster_field='scenario_family'),
            'item_extension_comparisons':comparisons(extension_pairs,methods,samples=samples,cluster_field='cluster_id'),
            'sql_equivalence':result['comparison'],
            'compatibility_note':'The 50 original questions and data are retained, but expanded-corpus distractors change retrieval competition. Compatibility here is not numerically equivalent to the original isolated top-five run; no isolated rerun is claimed.',
            'limitations':['This is a separate offline analysis; the source result bundle is not modified.',
                'Primary resampling units are scenario entities. Template-cluster sensitivity is also shown; neither makes synthetic scenarios independent real-world observations.',
                'Bonferroni simultaneous bootstrap intervals and Holm-adjusted permutation p-values answer different statistical questions; they are labeled separately.',
                'The item extension changes available result types and is not a like-for-like ranking improvement.',
                'Shared-machine timings remain diagnostic; these paired comparisons concern support, not speed.']}


def main():
    parser=add_provenance_argument(argparse.ArgumentParser())
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--samples',type=int,default=10000)
    args=parser.parse_args();run=BenchmarkRun(allow_dirty=args.allow_dirty)
    before=sha256(args.input)
    output=analyze(json.loads(args.input.read_text()),samples=args.samples)
    if sha256(args.input)!=before:raise RuntimeError('Input result changed during analysis')
    output.update(source_result_sha256=before,source_result_path=args.input.name)
    run.write_json(args.output,output)
    print(json.dumps({'output':str(args.output),'primary_queries':len(output['primary_query_ids']),
                      'comparisons':len(output['primary_comparisons']),'source_result_sha256':before}))


if __name__=='__main__':main()
