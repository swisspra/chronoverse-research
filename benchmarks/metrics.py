"""Deterministic retrieval metrics; qrels absent from tuning and ranking code."""
from __future__ import annotations
from collections import defaultdict
import math


def metrics_for_query(ranked_ids, qrels):
    relevant={doc:float(score) for doc,score in qrels.items() if score>0}
    ranked=list(dict.fromkeys(ranked_ids))
    gains=[relevant.get(doc,0) for doc in ranked[:10]]
    dcg=sum((2**gain-1)/math.log2(rank+2) for rank,gain in enumerate(gains))
    ideal=sum((2**gain-1)/math.log2(rank+2) for rank,gain in enumerate(sorted(relevant.values(),reverse=True)[:10]))
    rr=next((1/rank for rank,doc in enumerate(ranked[:10],1) if doc in relevant),0.0)
    return {"ndcg@10":dcg/ideal if ideal else 0.0,
            "recall@5":len(set(ranked[:5])&relevant.keys())/len(relevant) if relevant else 0.0,
            "recall@10":len(set(ranked[:10])&relevant.keys())/len(relevant) if relevant else 0.0,
            "mrr@10":rr,"hit@1":float(bool(ranked and ranked[0] in relevant))}


def aggregate_metrics(run,qrels):
    rows=[metrics_for_query(run.get(qid,[]),labels) for qid,labels in qrels.items()]
    names=("ndcg@10","recall@5","recall@10","mrr@10","hit@1")
    return {**{name:sum(row[name] for row in rows)/len(rows) if rows else 0.0 for name in names},"query_count":len(rows)}


def reciprocal_rank_fusion(rankings,k=60,limit=None):
    scores=defaultdict(float)
    for ranking in rankings:
        for rank,doc in enumerate(dict.fromkeys(ranking),1):
            scores[doc]+=1/(k+rank)
    return sorted(scores,key=lambda doc:(-scores[doc],doc))[:limit]


def latency_summary(seconds):
    values=sorted(seconds)
    def percentile(p):
        if not values:
            return None
        position=(len(values)-1)*p
        lo=math.floor(position)
        hi=math.ceil(position)
        return values[lo]+(values[hi]-values[lo])*(position-lo)
    return {"samples":len(values),"p50_seconds":percentile(.5),"p95_seconds":percentile(.95),"mean_seconds":sum(values)/len(values) if values else None,"total_seconds":sum(values)}


def paired_bootstrap_difference(left,right,samples=10000,seed=20260912):
    import numpy as np
    if len(left)!=len(right) or not left:
        raise ValueError("Paired bootstrap requires equal nonempty query arrays")
    differences=np.asarray(left,dtype=float)-np.asarray(right,dtype=float)
    rng=np.random.default_rng(seed)
    means=np.mean(differences[rng.integers(0,len(differences),size=(samples,len(differences)))],axis=1)
    low,high=np.quantile(means,[.025,.975])
    return {"mean_difference":float(np.mean(differences)),"ci95_low":float(low),"ci95_high":float(high),"queries":len(left),"samples":samples,"seed":seed}
