"""Harder synthetic temporal diagnostic; dev-calibrated gates never touch the app.

Gold is assigned explicitly by scenario authorship. Retrieval and eligibility do
not create gold. Disjoint entity and scenario families separate calibration/test.
"""
from __future__ import annotations
from benchmarks.provenance import BenchmarkRun, add_provenance_argument
import argparse
import argparse
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import random
import re
import time

ROOT = Path(__file__).resolve().parents[1]
SEED = 20260913
# Predeclared before viewing test outcomes. Gates retain order, never rerank.
ABSOLUTE_GRID = [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]
MARGIN_GRID = [0.02, 0.05, 0.10, 0.20, 1.00]
MIN_DEV_ANSWERABLE_COVERAGE = 0.60


def generate_fixture():
    rng = random.Random(SEED)
    opaque_ids = list(range(20000, 90000)); rng.shuffle(opaque_ids)
    rows, events, queries = [], [], []
    entity_sets = {'dev': ['Cedar', 'Amber', 'Birch', 'Copper'], 'test': ['Vesper', 'Lumen', 'Orchid', 'Cobalt', 'Morrow', 'Solace']}

    def add(entity, predicate, obj, *, start='2024-01-01', known='2024-01-01', end=None, plane='fact', perspective='general', world='main', evidence=None, evidence_known=None, summary=None):
        aid = f'v2-{opaque_ids.pop()}'
        text = evidence if evidence is not None else f'SYNTHETIC RECORD. {entity} {predicate} {obj}.'
        rows.append(dict(id=aid, subject=entity, predicate=predicate, object=obj, valid_from=start, recorded_at=known, valid_to=end, plane=plane, perspective=perspective, world=world,
                         summary=summary if summary is not None else f'{entity}: {predicate} {obj}.',
                         evidence=[dict(title='Synthetic scenario source', text=text, recorded_at=evidence_known or known, synthetic=True)]))
        return aid

    def event(aid, kind, effective, known, replacement=None):
        events.append(dict(id=f'v2-event-{len(events):04}', assertion_id=aid, type=kind, effective_at=effective, recorded_at=known, replacement_id=replacement, reason='Synthetic lifecycle policy: explicitly authored fixture transition.', source='Synthetic version bulletin'))

    def query(split, family, entity_key, wording, gold, *, valid='2024-07-01', known='2024-07-01', plane='fact', perspective='general', world='main', rationale, evidence_required=False):
        queries.append(dict(id=f'v2-q-{len(queries):04}', split=split, family=family, entity_key=entity_key, query=wording,
                            scope=dict(valid_at=valid, known_at=known, plane=plane, perspective=perspective, world=world),
                            gold_assertion_ids=list(gold), rationale=rationale, evidence_required=evidence_required))

    for split, names in entity_sets.items():
        for name in names:
            entity = f'{name} Observatory'
            # Both splits contain hard competing predicates and near-name entities;
            # the held-out questions use distinct lifecycle/scenario families.
            direct = add(entity, 'director', 'Mira Vale')
            funding = add(entity, 'funding director', 'Iris North')
            add(entity, 'former board adviser', 'Theo Reed')
            annex = add(f'{entity} Annex', 'director', 'Nora Hale')
            capacity = add(entity, 'visitor capacity', '240 people')
            attendance = add(entity, 'annual visitor count', '24000 people')
            add(entity, 'telescope aperture', '2.4 meters')
            office = add(entity, 'headquarters location', 'Pine Harbor')
            add(entity, 'satellite station location', 'West Ridge')
            otherworld = add(entity, 'director', 'Ari Lane', world='planning')
            health = add(f'{name} reservoir', 'water safety', 'safe', plane='report', perspective='municipal')
            add(f'{name} reservoir', 'water safety', 'unsafe', plane='report', perspective='independent laboratory')

            if split == 'dev':
                replacement = add(entity, 'director', 'Bea Rowan', start='2024-06-01', known='2024-06-05')
                event(direct, 'supersede', '2024-06-01', '2024-06-05', replacement)
                query(split,'dev_delayed_appointment',name,f'Who leads {entity}?',[direct],valid='2024-06-02',known='2024-06-04',rationale='The effective appointment is not learned until June 5.')
                query(split,'dev_delayed_appointment',name,f'Who leads {entity}?',[replacement],valid='2024-06-02',known='2024-06-06',rationale='After June 5 knowledge, the replacement covers June 2.')
                query(split,'dev_numeric_predicate',name,f'How many guests can {entity} accommodate?',[capacity],rationale='Capacity is not annual attendance or telescope aperture.')
                query(split,'dev_location_paraphrase',name,f'Where is the main office of {entity}?',[office],rationale='Headquarters, not the satellite station.')
                query(split,'dev_world_scope',name,f'Who is the head of {entity} in the planning world?',[otherworld],world='planning',rationale='Only the supplied planning world is eligible.')
                query(split,'dev_perspective',name,f'According to the municipality, is the water in {name} reservoir safe?',[health],plane='report',perspective='municipal',rationale='The named perspective supplies this report; it is not a truth adjudication.')
                rumor = add(f'{name} bridge','structural condition','collapsed',plane='report',start='2024-06-01',known='2024-06-01')
                event(rumor,'retract','2024-06-01','2024-06-03')
                query(split,'dev_withdrawn_report',name,f'What is the reported structural condition of {name} bridge?',[],plane='report',rationale='The only target report has been retracted.')
                query(split,'dev_missing_attribute',name,f'What is the postal code of {entity}?',[],rationale='No assertion or evidence states a postal code; location is not an answer.')
                one = add(f'{name} park','reopening date','June 11',plane='report')
                two = add(f'{name} park','reopening date','June 12',plane='report')
                query(split,'dev_disagreement',name,f'Which reopening dates are reported for {name} park?',[one,two],plane='report',rationale='Two unresolved reports must remain in the answer set.')
                permit = add(f'{name} permit','access status','authorized',end='2024-06-01')
                query(split,'dev_expired_permission',name,f'Is access under {name} permit authorized?',[],rationale='The half-open permit interval ended June 1.')
            else:
                # Two replacements; learned later than their valid-time boundaries.
                second = add(entity,'director','Bea Rowan',start='2024-05-01',known='2024-05-04')
                third = add(entity,'director','Cy Morgan',start='2024-06-01',known='2024-06-08')
                event(direct,'supersede','2024-05-01','2024-05-04',second)
                event(second,'supersede','2024-06-01','2024-06-08',third)
                query(split,'test_chained_succession',name,f'Who was running {entity} on the selected date?',[second],valid='2024-06-02',known='2024-06-07T23:59:59.999999Z',rationale='The third appointment is still unknown; the second remains usable.')
                query(split,'test_chained_succession',name,f'Who was running {entity} on the selected date?',[third],valid='2024-06-02',known='2024-06-08T00:00:00Z',rationale='At the exact knowledge boundary, the third appointment becomes known.')
                query(split,'test_historical_after_chain',name,f'Identify the person directing {entity} in April.',[direct],valid='2024-04-30',known='2024-07-01',rationale='Later supersession must not erase earlier valid-time applicability.')
                query(split,'test_confusable_role',name,f'Name the person responsible for funding at {entity}.',[funding],rationale='Funding director is a different predicate from observatory director.')
                query(split,'test_confusable_quantity',name,f'How many people visited {entity} over a year?',[attendance],rationale='Annual attendance must not be confused with simultaneous capacity.')
                query(split,'test_near_name_entity',name,f'Who heads the Annex of {entity}?',[annex],rationale='The Annex is a different entity, despite overlapping name tokens.')
                storm=f'{name} storm'
                original=add(storm,'injured count','18',start='2024-06-01',known='2024-06-01',plane='report')
                revised=add(storm,'injured count','8',start='2024-06-01',known='2024-06-03',plane='report')
                final=add(storm,'injured count','3',start='2024-06-01',known='2024-06-05',plane='report')
                event(original,'correct','2024-06-01','2024-06-03',revised)
                event(revised,'correct','2024-06-01','2024-06-05',final)
                query(split,'test_chained_corrections',name,f'How many people were hurt in {storm}?',[revised],plane='report',valid='2024-06-01',known='2024-06-04T23:59:59.999999Z',rationale='The second correction is not known before June 5.')
                query(split,'test_chained_corrections',name,f'How many people were hurt in {storm}?',[final],plane='report',valid='2024-06-01',known='2024-06-05T00:00:00Z',rationale='Exactly at recorded time, the second correction retires the intermediate count.')
                slot=add(f'{name} access slot','entry permission','granted',start='2024-06-01T12:00:00.123456Z',end='2024-06-01T12:00:01.123456Z')
                query(split,'test_microsecond_interval',name,f'May someone enter using the {name} access slot?',[],valid='2024-06-01T12:00:00.123455Z',rationale='One microsecond before valid_from is outside the interval.')
                query(split,'test_microsecond_interval',name,f'May someone enter using the {name} access slot?',[slot],valid='2024-06-01T12:00:00.123456Z',rationale='The valid_from boundary is inclusive.')
                query(split,'test_microsecond_interval',name,f'May someone enter using the {name} access slot?',[],valid='2024-06-01T12:00:01.123456Z',rationale='The valid_to boundary is exclusive.')
                dossier=add(f'{name} archive','contains','inspection note',summary='An archived inspection note; its passage becomes available separately.',evidence=f'SYNTHETIC INSPECTION NOTE. The odor at {name} warehouse was caused by a leaking ammonia valve.',evidence_known='2024-06-03T10:30:00Z')
                query(split,'test_late_evidence',name,f'What caused the odor at {name} warehouse?',[],known='2024-06-03T10:29:59.999999Z',rationale='The answer occurs only in the evidence passage, which is not yet known.',evidence_required=True)
                query(split,'test_late_evidence',name,f'What caused the odor at {name} warehouse?',[dossier],known='2024-06-03T10:30:00Z',rationale='At the exact evidence recorded time, the passage supports the query.',evidence_required=True)
                report=add(f'{name} waterline','leak status','detected',start='2024-06-01',known='2024-06-01',plane='report')
                event(report,'retract','2024-06-01','2024-06-04T09:00:00Z')
                query(split,'test_retraction_boundary',name,f'Was a leak reported in the {name} waterline?',[report],plane='report',known='2024-06-04T08:59:59.999999Z',rationale='The retraction is not yet known.')
                query(split,'test_retraction_boundary',name,f'Was a leak reported in the {name} waterline?',[],plane='report',known='2024-06-04T09:00:00Z',rationale='At the exact recorded boundary, the report is retracted.')
                conflict1=add(f'{name} airfield','closure date','July 9',plane='report',perspective='wire')
                conflict2=add(f'{name} airfield','closure date','July 10',plane='report',perspective='wire')
                add(f'{name} airfield','inspection date','July 8',plane='report',perspective='wire')
                query(split,'test_predicate_conflict',name,f'Which dates do wire reports give for shutting {name} airfield?',[conflict1,conflict2],plane='report',perspective='wire',rationale='Both incompatible closure reports count; the inspection date does not.')
                query(split,'test_missing_relation',name,f'What is the emergency telephone number of {entity}?',[],rationale='There is no telephone-number evidence; nearby administrative facts are unrelated.')
                query(split,'test_nonexistent_entity',name,f'Who directs {name} Planetarium?',[],rationale='No Planetarium was indexed; the similarly named Observatory is not the same entity.')
                query(split,'test_unrecorded_future',name,f'Who will take charge of {entity} in 2035?',[],valid='2035-01-01',known='2024-07-01',rationale='No future appointment is asserted. An open-ended current director does not answer who will take charge in 2035.')
    rng.shuffle(rows); rng.shuffle(queries)
    return dict(name='Temporal v2 held-out synthetic diagnostic',seed=SEED,synthetic=True,
                disclaimer='Manually authored synthetic capability and selective-retrieval diagnostic, not a public temporal QA benchmark or an evaluation of truth. Gold was not generated from Store.',
                entity_splits=entity_sets,assertions=rows,events=events,queries=queries,
                split_policy='Disjoint entity names and disjoint scenario families. DEV only chooses gates. TEST judgments never select parameters. Shared domain vocabulary remains a limitation.',
                gate_protocol=dict(absolute_cosine=ABSOLUTE_GRID,relative_margin=MARGIN_GRID,min_dev_answerable_coverage=MIN_DEV_ANSWERABLE_COVERAGE,objective='Maximize DEV micro F0.5 among gates meeting answerable coverage >=0.60; ties prefer recall, precision, lower absolute threshold, larger margin. No candidate reranking.'))


def instant(value):
    value=datetime.fromisoformat(value.replace('Z','+00:00'))
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def visible_record(row, scope, events):
    """Independent reference policy, inspecting metadata/events but never gold."""
    valid,known=instant(scope['valid_at']),instant(scope['known_at'])
    if any(scope[key]!='all' and row[key]!=scope[key] for key in ('world','plane','perspective')):return None
    if instant(row['recorded_at'])>known or instant(row['valid_from'])>valid:return None
    if row['valid_to'] is not None and instant(row['valid_to'])<=valid:return None
    if any(instant(event['recorded_at'])<=known and instant(event['effective_at'])<=valid for event in events.get(row['id'],[])):return None
    projected=dict(row)
    projected['evidence']=[e for e in row['evidence'] if instant(e['recorded_at'])<=known]
    return projected


def canonical_text(row):
    return ' '.join([row['subject'],row['predicate'],row['object'],row['summary'],*[e['text'] for e in row['evidence']]])


def tokens(text):return re.findall(r'[^\W_]+',text.casefold(),re.UNICODE)


def apply_gate(ranking, dense_scores, absolute, margin):
    if not ranking:return []
    best=max(dense_scores[aid] for aid in ranking)
    return [aid for aid in ranking if dense_scores[aid]>=absolute and dense_scores[aid]>=best-margin]


def selective_metrics(run, queries):
    from benchmarks.metrics import aggregate_metrics
    tp=fp=fn=covered=false_abstained=empty_abstained=exact=conflict_complete=conflicts=0
    answerable=[q for q in queries if q['gold_assertion_ids']]
    for query in queries:
        got=set(run.get(query['id'],[])[:10]); gold=set(query['gold_assertion_ids'])
        tp+=len(got&gold);fp+=len(got-gold);fn+=len(gold-got);covered+=bool(got);exact+=got==gold
        if gold:false_abstained+=not got
        else:empty_abstained+=not got
        if len(gold)>1:conflicts+=1;conflict_complete+=gold<=got
    precision=tp/(tp+fp) if tp+fp else 0.0;recall=tp/(tp+fn) if tp+fn else 0.0
    f05=1.25*precision*recall/(.25*precision+recall) if precision+recall else 0.0
    return {**aggregate_metrics(run,{q['id']:{aid:1 for aid in q['gold_assertion_ids']} for q in answerable}),
            'total_queries':len(queries),'empty_gold_queries':len(queries)-len(answerable),'true_positives':tp,'false_positives':fp,'false_negatives':fn,
            'micro_precision':precision,'micro_recall':recall,'micro_f0.5':f05,'coverage':covered/len(queries),
            'answerable_coverage':1-false_abstained/len(answerable),'false_abstention_rate':false_abstained/len(answerable),
            'empty_gold_abstention_rate':empty_abstained/(len(queries)-len(answerable)) if len(queries)>len(answerable) else None,
            'exact_set_rate':exact/len(queries),'conflict_complete_rate':conflict_complete/conflicts if conflicts else None}


def calibrate(dev_queries, rankings, dense_scores):
    candidates=[]
    for absolute in ABSOLUTE_GRID:
        for margin in MARGIN_GRID:
            run={q['id']:apply_gate(rankings[q['id']],dense_scores[q['id']],absolute,margin) for q in dev_queries}
            metrics=selective_metrics(run,dev_queries)
            candidates.append(dict(absolute_cosine=absolute,relative_margin=margin,dev_metrics=metrics))
    feasible=[row for row in candidates if row['dev_metrics']['answerable_coverage']>=MIN_DEV_ANSWERABLE_COVERAGE]
    pool=feasible or candidates
    selected=max(pool,key=lambda row:(row['dev_metrics']['micro_f0.5'],row['dev_metrics']['micro_recall'],row['dev_metrics']['micro_precision'],-row['absolute_cosine'],row['relative_margin']))
    return selected,candidates,bool(feasible)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--fixture',type=Path,default=ROOT/'benchmarks/data/temporal-v2.json')
    parser.add_argument('--output',type=Path,default=ROOT/'docs/benchmarks-v2/temporal-results.json')
    parser.add_argument('--generate-only',action='store_true')
    add_provenance_argument(parser);args=parser.parse_args();benchmark_run=BenchmarkRun(allow_dirty=args.allow_dirty)
    fixture=generate_fixture();args.fixture.parent.mkdir(parents=True,exist_ok=True)
    serialized=json.dumps(fixture,indent=2,ensure_ascii=False)+'\n'
    if args.fixture.exists() and args.fixture.read_text()!=serialized:raise RuntimeError('Existing fixture differs: review fixture version explicitly rather than overwriting gold.')
    args.fixture.write_text(serialized)
    print(json.dumps({'stage':'fixture_frozen','assertions':len(fixture['assertions']),'events':len(fixture['events']),'dev':sum(q['split']=='dev' for q in fixture['queries']),'test':sum(q['split']=='test' for q in fixture['queries']),'sha256':sha256(serialized.encode()).hexdigest()}),flush=True)
    if args.generate_only:return
    import numpy as np
    from rank_bm25 import BM25Okapi
    from chronoverse.models import AssertionInput,EventInput,QueryRequest
    from chronoverse.store import Store
    from chronoverse import semantic
    from benchmarks.metrics import reciprocal_rank_fusion,latency_summary
    os.environ['CHRONOVERSE_EMBEDDINGS']='semantic'
    source_before={name:sha256((ROOT/'backend/chronoverse'/name).read_bytes()).hexdigest() for name in ('store.py','semantic.py','models.py')}
    by_id={row['id']:row for row in fixture['assertions']};events=defaultdict(list)
    for event in fixture['events']:events[event['assertion_id']].append(event)
    store=Store(':memory:',seed=False)
    for row in fixture['assertions']:store.add_assertion(AssertionInput(**row))
    for event in fixture['events']:store.add_event(event['assertion_id'],EventInput(**{k:v for k,v in event.items() if k!='assertion_id'}))
    methods=['BM25 + reference scope/evidence','Dense + reference scope/evidence','RRF + reference scope/evidence','Chronoverse actual Store']
    runs={name:{} for name in methods};timings={name:[] for name in methods};dense_scores={};index_start=time.perf_counter();vectors={}
    def vector(text):
        if text not in vectors:
            arr=np.asarray(semantic._embed(text),dtype=float);vectors[text]=arr/(np.linalg.norm(arr) or 1)
        return vectors[text]
    # Materialize only independently projected evidence-visible text variants.
    projections={}
    for query in fixture['queries']:
        allowed=[projected for row in fixture['assertions'] if (projected:=visible_record(row,query['scope'],events)) is not None]
        allowed.sort(key=lambda row:row['id']);projections[query['id']]=allowed
        for row in allowed:vector(canonical_text(row))
        vector(query['query'])
    vector_seconds=time.perf_counter()-index_start
    try:
        for index,query in enumerate(fixture['queries']):
            qid=query['id'];allowed=projections[qid];ids=[row['id'] for row in allowed];texts=[canonical_text(row) for row in allowed];qv=vector(query['query'])
            clock=time.perf_counter();bm25=BM25Okapi([tokens(text) for text in texts]) if texts else None
            bm_scores=bm25.get_scores(tokens(query['query'])) if bm25 else []
            bm=sorted(range(len(ids)),key=lambda i:(-bm_scores[i],ids[i]));timings[methods[0]].append(time.perf_counter()-clock)
            clock=time.perf_counter();scores=[float(vector(text)@qv) for text in texts];dense=sorted(range(len(ids)),key=lambda i:(-scores[i],ids[i]));timings[methods[1]].append(time.perf_counter()-clock)
            bm_ids=[ids[i] for i in bm];dense_ids=[ids[i] for i in dense]
            clock=time.perf_counter();rrf=reciprocal_rank_fusion([bm_ids,dense_ids],k=60,limit=10);timings[methods[2]].append(time.perf_counter()-clock+timings[methods[0]][-1]+timings[methods[1]][-1])
            runs[methods[0]][qid]=bm_ids[:10];runs[methods[1]][qid]=dense_ids[:10];runs[methods[2]][qid]=rrf
            clock=time.perf_counter();actual=store.query(QueryRequest(query=query['query'],**query['scope'],limit=10));timings[methods[3]].append(time.perf_counter()-clock)
            runs[methods[3]][qid]=[row['id'] for row in actual['results']]
            dense_scores[qid]=dict(zip(ids,scores))
            unknown=set(runs[methods[3]][qid])-set(ids)
            if unknown:raise AssertionError(f'Actual Store returned coordinate-ineligible IDs {qid}: {unknown}')
            if (index+1)%30==0:print(json.dumps({'stage':'retrieval','complete':index+1,'total':len(fixture['queries'])}),flush=True)
    finally:store.close()
    source_after={name:sha256((ROOT/'backend/chronoverse'/name).read_bytes()).hexdigest() for name in source_before}
    if source_before!=source_after:raise RuntimeError('Production implementation changed during run; discard this run and retry after code stabilizes.')
    dev=[q for q in fixture['queries'] if q['split']=='dev'];test=[q for q in fixture['queries'] if q['split']=='test'];systems={}
    for name in methods:
        selected,grid,feasible=calibrate(dev,runs[name],dense_scores)
        frozen={key:selected[key] for key in ('absolute_cosine','relative_margin')};gate_hash=sha256(json.dumps(frozen,sort_keys=True).encode()).hexdigest()
        gated={q['id']:apply_gate(runs[name][q['id']],dense_scores[q['id']],frozen['absolute_cosine'],frozen['relative_margin']) for q in fixture['queries']}
        systems[name]=dict(frozen_gate=frozen,frozen_gate_sha256=gate_hash,dev_coverage_constraint_met=feasible,calibration_grid=grid,
                           non_gated={split:selective_metrics(runs[name],part) for split,part in [('dev',dev),('test',test)]},
                           gated={split:selective_metrics(gated,part) for split,part in [('dev',dev),('test',test)]},rankings=runs[name],gated_rankings=gated,retrieval_timing=latency_summary(timings[name]))
        print(json.dumps({'stage':'held_out_results','system':name,'frozen_gate':frozen,'test_non_gated':systems[name]['non_gated']['test'],'test_gated':systems[name]['gated']['test']}),flush=True)
    payload=dict(track='held-out synthetic temporal selective retrieval v2',created_at=datetime.now(timezone.utc).isoformat(),fixture_sha256=sha256(serialized.encode()).hexdigest(),
                 assertions=len(fixture['assertions']),events=len(fixture['events']),dev_queries=len(dev),test_queries=len(test),entity_splits=fixture['entity_splits'],
                 scenario_families={split:sorted({q['family'] for q in part}) for split,part in [('dev',dev),('test',test)]},gate_protocol=fixture['gate_protocol'],systems=systems,queries=fixture['queries'],
                 protocol=['All gold is explicitly scenario-authored; test never selects gates.','Every comparator receives exact coordinates, lifecycle policy, and only knowledge-visible evidence text.','Reference BM25 is rebuilt on each eligible snapshot, so document frequencies cannot leak future evidence. Dense vectors use identical canonical text.','Gates filter each method top-10 pool using independent MiniLM cosine; candidate order remains unchanged.','Warm embeddings and per-snapshot BM25 fitting have different pipeline costs; timings are diagnostics, not a matched production throughput comparison.','No gate or ranking heuristic was deployed to the application.'],
                 limitations=['Synthetic domain with shared vocabulary across disjoint entities/scenario families; not independently authored public temporal QA.','The top-10 candidate pool limits gated recall; absolute cosine is not a calibrated truth probability.','No automatic extraction, answer generation, factual verification, or user-document evaluation.','Historical/future question gold encodes explicit intent: an open-ended current incumbent does not answer an unasserted future appointment.'],
                 source_sha256=source_before,model=semantic.MODEL,embedding_variants=len(vectors),embedding_preparation_seconds=vector_seconds,platform=platform.platform(),versions={p:importlib.metadata.version(p) for p in ('fastembed','numpy','rank-bm25','chronoverse')})
    args.output.parent.mkdir(parents=True,exist_ok=True);benchmark_run.write_json(args.output, payload)
    print(json.dumps({'stage':'complete','output':str(args.output)}),flush=True)


if __name__=='__main__':main()
