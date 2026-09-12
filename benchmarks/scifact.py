"""Reproducible SciFact benchmark of stock Store.query and explicit baselines.

No app data is read or written. The full query run changes only the benchmark
process's embedding-cache capacity; production scoring/filtering stays untouched.
"""
from __future__ import annotations
from benchmarks.provenance import BenchmarkRun, add_provenance_argument
import argparse
import argparse
from collections import defaultdict
from contextlib import contextmanager
import csv
from datetime import datetime,timezone
from functools import lru_cache
import hashlib
from importlib.metadata import version
import inspect
import json
import os
from pathlib import Path
import platform
import resource
import tempfile
import time
import urllib.request
import zipfile

from chronoverse.models import AssertionInput,QueryRequest
from chronoverse.store import Store,_text,_tokens
from benchmarks.metrics import aggregate_metrics,metrics_for_query,reciprocal_rank_fusion,latency_summary,paired_bootstrap_difference

ROOT=Path(__file__).resolve().parents[1]
DATA_URL="https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip"
OFFICIAL_MD5="5f7d1de60b170fc8027bb7898e2efca1"
SOURCES={"dataset_archive":DATA_URL,"beir_repository":"https://github.com/beir-cellar/beir","original_scifact":"https://github.com/allenai/scifact","dataset_license_card":"https://huggingface.co/datasets/BeIR/scifact/blob/main/README.md","dataset_license":"CC-BY-SA-4.0 (BEIR SciFact dataset card)","beir_paper":"https://openreview.net/forum?id=wCu6T5xFjeJ","scifact_paper":"https://aclanthology.org/2020.emnlp-main.609/"}


def emit(stage,**details):
    print(json.dumps({"stage":stage,**details}),flush=True)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def download_dataset(directory):
    directory.mkdir(parents=True,exist_ok=True)
    archive=directory/"scifact.zip"
    if not archive.exists():
        with urllib.request.urlopen(DATA_URL,timeout=60) as response:
            content=response.read()
        temporary=directory/"scifact.zip.partial"
        temporary.write_bytes(content)
        temporary.replace(archive)
    content=archive.read_bytes()
    if hashlib.md5(content).hexdigest()!=OFFICIAL_MD5:
        raise ValueError("SciFact archive does not match official BEIR MD5")
    hashes={"scifact.zip":digest(archive)}
    with zipfile.ZipFile(archive) as zipped:
        for member in ("corpus.jsonl","queries.jsonl","qrels/test.tsv"):
            target=directory/member
            target.parent.mkdir(parents=True,exist_ok=True)
            data=zipped.read("scifact/"+member)
            target.write_bytes(data)
            hashes[member]=hashlib.sha256(data).hexdigest()
    corpus=[json.loads(line) for line in (directory/"corpus.jsonl").read_text().splitlines()]
    all_queries={row["_id"]:row["text"] for row in map(json.loads,(directory/"queries.jsonl").read_text().splitlines())}
    qrels=defaultdict(dict)
    with (directory/"qrels/test.tsv").open() as source:
        for row in csv.DictReader(source,delimiter="\t"):
            if int(row["score"])>0:
                qrels[row["query-id"]][row["corpus-id"]]=int(row["score"])
    queries={qid:all_queries[qid] for qid in sorted(qrels,key=lambda q:int(q))}
    assert len(corpus)==5183 and len(queries)==300
    assert all(doc in {row["_id"] for row in corpus} for labels in qrels.values() for doc in labels)
    return sorted(corpus,key=lambda row:row["_id"]),queries,dict(qrels),hashes


def canonical_assertion(document):
    doc_id=document["_id"]
    return AssertionInput(id=f"scifact-{doc_id}",subject=f"SciFact document {doc_id}",predicate="contains",object=f"Abstract {doc_id}",world="main",plane="report",perspective="scifact",valid_from="2000-01-01",recorded_at="2000-01-01",summary="",evidence=[{"title":"SciFact source abstract","text":document["title"]+"\n"+document["text"],"synthetic":False}])


@contextmanager
def enlarged_embedding_cache(corpus_texts=None):
    from chronoverse import semantic
    stock=semantic._embed
    cached=lru_cache(maxsize=None)(stock.__wrapped__)
    if corpus_texts is None:
        semantic._embed=cached
    else:
        document_texts=set(corpus_texts)
        def document_cache_only(text):
            # Never reuse query encodings: all dense methods measure a fresh encode.
            return cached(text) if text in document_texts else stock.__wrapped__(text)
        document_cache_only.__wrapped__=stock.__wrapped__
        semantic._embed=document_cache_only
    try:
        yield cached
    finally:
        semantic._embed=stock


def ranked(scores,doc_ids,limit=1000):
    return sorted(range(len(doc_ids)),key=lambda index:(-float(scores[index]),doc_ids[index]))[:limit]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data-dir",type=Path,default=ROOT/".benchmark-data/scifact")
    parser.add_argument("--output",type=Path,default=ROOT/"docs/benchmarks/scifact-results.json")
    parser.add_argument("--stock-pilot-queries",type=int,default=2)
    parser.add_argument("--max-queries",type=int,default=300)
    parser.add_argument("--resume-stock-pilot",action="store_true")
    add_provenance_argument(parser);args=parser.parse_args();benchmark_run=BenchmarkRun(allow_dirty=args.allow_dirty)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    os.environ["CHRONOVERSE_EMBEDDINGS"]="semantic"
    os.environ.setdefault("CHRONOVERSE_MODEL_CACHE",str(ROOT/".model-cache"))
    from chronoverse import semantic
    from rank_bm25 import BM25Okapi
    import numpy as np
    started=time.perf_counter()
    corpus,queries,qrels,hashes=download_dataset(args.data_dir)
    queries=dict(list(queries.items())[:args.max_queries])
    qrels={qid:qrels[qid] for qid in queries}
    doc_ids=[row["_id"] for row in corpus]
    emit("dataset_ready",documents=len(corpus),queries=len(queries),hashes=hashes)
    timing={"download_load_seconds":time.perf_counter()-started}
    records=[canonical_assertion(row) for row in corpus]
    with tempfile.TemporaryDirectory(prefix="scifact-ledger-",dir=args.data_dir) as temporary:
        store=Store(Path(temporary)/"ledger.sqlite3",seed=False)
        clock=time.perf_counter()
        for offset in range(0,len(records),500):
            store.add_assertions_atomic(records[offset:offset+500])
        timing["ledger_index_seconds"]=time.perf_counter()-clock
        canonical_texts=[_text(store.get_assertion(record.id)) for record in records]
        canonical_hash=hashlib.sha256("\n".join(canonical_texts).encode()).hexdigest()
        (args.data_dir/"canonical-records.jsonl").write_text("".join(json.dumps({"doc_id":doc_id,"text":text})+"\n" for doc_id,text in zip(doc_ids,canonical_texts)))
        emit("ledger_indexed",seconds=timing["ledger_index_seconds"],documents=len(records),canonical_text_sha256=canonical_hash)
        stock_rows=[]
        pilot_path=args.output.with_name("scifact-stock-pilot.json")
        if args.resume_stock_pilot and pilot_path.exists():
            prior=json.loads(pilot_path.read_text())
            assert prior["indexed_count"]==len(records)
            stock_rows=prior["rows"]
        for index,(qid,query) in enumerate(list(queries.items())[:args.stock_pilot_queries]):
            if index<len(stock_rows):
                continue
            clock=time.perf_counter()
            before=semantic._embed.cache_info()
            result=store.query(QueryRequest(query=query,world="main",plane="report",perspective="scifact",limit=10))
            elapsed=time.perf_counter()-clock
            after=semantic._embed.cache_info()
            row={"query_id":qid,"seconds":elapsed,"cache_hits":after.hits-before.hits,"cache_misses":after.misses-before.misses,"ranked_ids":[item["id"].removeprefix("scifact-") for item in result["results"]],"ranked_scores":[item["score"] for item in result["results"]],"cold_model":index==0}
            stock_rows.append(row)
            emit("stock_pilot",**row)
            benchmark_run.write_json(args.output.with_name("scifact-stock-pilot.json"), {"indexed_count":len(records),"rows":stock_rows})
        runs={name:{} for name in ("bm25","dense_minilm","rrf_bm25_dense","chronoverse_store_optimized_cache")}
        latencies={name:[] for name in runs}
        per_query=[]
        with enlarged_embedding_cache(canonical_texts) as cached:
            clock=time.perf_counter()
            vectors=[]
            for index,text in enumerate(canonical_texts):
                vectors.append(cached(text))
                if (index+1)%500==0:
                    emit("embedding_index_progress",documents=index+1,seconds=time.perf_counter()-clock)
            timing["embedding_index_seconds"]=time.perf_counter()-clock
            matrix=np.asarray(vectors,dtype=np.float64)
            norms=np.linalg.norm(matrix,axis=1)
            matrix=matrix/np.maximum(norms[:,None],1e-30)
            np.save(args.data_dir/"document-embeddings.npy",matrix)
            emit("embeddings_indexed",seconds=timing["embedding_index_seconds"],shape=list(matrix.shape))
            clock=time.perf_counter()
            bm25=BM25Okapi([_tokens(text) for text in canonical_texts],k1=1.5,b=.75,epsilon=.25)
            timing["bm25_index_seconds"]=time.perf_counter()-clock
            equivalence=[]
            for original in stock_rows:
                result=store.query(QueryRequest(query=queries[original["query_id"]],world="main",plane="report",perspective="scifact",limit=10))
                same_ids=[item["id"].removeprefix("scifact-") for item in result["results"]]==original["ranked_ids"]
                same_scores=[item["score"] for item in result["results"]]==original["ranked_scores"]
                equivalence.append({"query_id":original["query_id"],"exact_top10_ids":same_ids,"exact_scores":same_scores})
                if not same_ids or not same_scores:
                    raise AssertionError("Benchmark-only cache changed Store.query outputs")
            # Every timed query includes live uncached query encoding; only documents are cached.
            for number,(qid,query) in enumerate(queries.items(),1):
                query_row={"query_id":qid,"metrics":{},"latency_seconds":{}}
                clock=time.perf_counter()
                bm_scores=bm25.get_scores(_tokens(query))
                bm_rank=[doc_ids[i] for i in ranked(bm_scores,doc_ids)]
                bm_elapsed=time.perf_counter()-clock
                runs["bm25"][qid]=bm_rank[:10]
                latencies["bm25"].append(bm_elapsed)
                # Uncached query encode makes dense timing include current model inference.
                clock=time.perf_counter()
                q=np.asarray(semantic._embed.__wrapped__(query),dtype=np.float64)
                q=q/max(float(np.linalg.norm(q)),1e-30)
                dscores=matrix@q
                dense_rank=[doc_ids[i] for i in ranked(dscores,doc_ids)]
                dense_elapsed=time.perf_counter()-clock
                runs["dense_minilm"][qid]=dense_rank[:10]
                latencies["dense_minilm"].append(dense_elapsed)
                clock=time.perf_counter()
                fused=reciprocal_rank_fusion([bm_rank,dense_rank],k=60,limit=10)
                fusion_elapsed=time.perf_counter()-clock
                runs["rrf_bm25_dense"][qid]=fused
                latencies["rrf_bm25_dense"].append(bm_elapsed+dense_elapsed+fusion_elapsed)
                clock=time.perf_counter()
                result=store.query(QueryRequest(query=query,world="main",plane="report",perspective="scifact",limit=10))
                chrono_elapsed=time.perf_counter()-clock
                runs["chronoverse_store_optimized_cache"][qid]=[item["id"].removeprefix("scifact-") for item in result["results"]]
                latencies["chronoverse_store_optimized_cache"].append(chrono_elapsed)
                for name in runs:
                    query_row["metrics"][name]=metrics_for_query(runs[name][qid],qrels[qid])
                    query_row["latency_seconds"][name]=latencies[name][-1]
                per_query.append(query_row)
                if number%10==0:
                    emit("queries_evaluated",completed=number,total=len(queries),elapsed_seconds=time.perf_counter()-started)
                # Persist progress so a long run never loses completed measurements.
                if number%50==0:
                    benchmark_run.write_json(args.output.with_name("scifact-progress.json"), {"completed":number,"metrics":{name:aggregate_metrics(run,{key:qrels[key] for key in run}) for name,run in runs.items()}})
            for name,run in runs.items():
                benchmark_run.write_json(args.output.with_name(f"scifact-{name}.run.json"), {"rankings":run})
        store.close()
    result={"benchmark":"BEIR SciFact test retrieval","created_at":datetime.now(timezone.utc).isoformat(),"status":"complete","indexed_count":len(corpus),"test_query_count":len(queries),"sources":SOURCES,"sha256":hashes,"official_archive_md5":OFFICIAL_MD5,"canonical_text_sha256":canonical_hash,"canonical_text":"Exact chronoverse.store._text over one report-plane assertion per SciFact abstract: subject SciFact document <id>, predicate contains, object Abstract <id>, empty summary, evidence text title + newline + abstract. Same canonical strings used by all four methods.","parameters":{"bm25":{"implementation":"rank-bm25.BM25Okapi","k1":1.5,"b":.75,"epsilon":.25,"tokenizer":"chronoverse.store._tokens; Unicode alphanumeric casefold; no stemming/stopwords"},"dense":{"model":semantic.MODEL,"dimensions":384,"similarity":"exact float64 cosine over original single-document backend embeddings; no ANN","query_encoding":"original uncached embedding function"},"rrf":{"k":60,"retrievers":["bm25","dense_minilm"],"fusion_depth":1000},"chronoverse":{"entrypoint":"chronoverse.store.Store.query","production_weights":{"lexical":.35,"vector":.5,"graph":.15},"semantic_threshold":.28,"only_optimization":"benchmark process semantic._embed LRU maxsize2048 replaced by unbounded document-only memoization of same original function; queries always encoded fresh; no scorer/filter/ranking replacement"},"scope":{"world":"main","plane":"report","perspective":"scifact","valid_at":"2026-09-12","known_at":"2026-09-12"}},"stock_pilot":{"indexed_count":len(corpus),"production_cache_size":2048,"rows":stock_rows,"latency":latency_summary([row["seconds"] for row in stock_rows]),"warning":"Pilot samples are too few for stable p95. First includes model initialization; subsequent full-corpus scan still thrashes cache."},"cache_equivalence":equivalence,"methods":{name:{"metrics":aggregate_metrics(run,qrels),"warm_latency":latency_summary(latencies[name])} for name,run in runs.items()},"index_timings":timing,"total_wall_seconds":time.perf_counter()-started,"environment":{"python":platform.python_version(),"platform":platform.platform(),"machine":platform.machine(),"cpu_count":os.cpu_count(),"onnx_threads":2,"versions":{name:version(name) for name in ("chronoverse","fastembed","onnxruntime","numpy","rank-bm25")},"max_rss_platform_units":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},"production_source_sha256":{name:digest(ROOT/"backend/chronoverse"/name) for name in ("store.py","semantic.py","models.py")},"per_query":per_query,"limitations":["This is scientific document retrieval, not claim verification, temporal reasoning, or full GraphRAG evaluation.","One abstract per assertion and unique document/passage entities provide no independently extracted scientific entity graph; graph self-support is often a constant bonus.","All methods receive identical canonical record text; scores are not directly comparable to official BEIR leaderboard runs with different text preprocessing or models.","Full Chronoverse accuracy run uses explicitly enlarged benchmark-only cache; full-run latency is not stock application latency.","No test qrels were used to select parameters, prompts, corpus documents or test queries.","CPU benchmarks may overlap other local work; use a controlled idle machine for deployment capacity estimates.","Embedding model token limits can truncate long abstracts; identical underlying embeddings feed dense and Chronoverse methods."]}
    result["timing_accounting"]={"resumed_stock_pilot":args.resume_stock_pilot,"current_process_wall_seconds":result["total_wall_seconds"],"stock_pilot_seconds":sum(row["seconds"] for row in stock_rows),"note":"When resumed_stock_pilot=true, current process wall time excludes the separately reported earlier stock pilot."}
    chrono_values=[row["metrics"]["chronoverse_store_optimized_cache"]["ndcg@10"] for row in per_query]
    result["paired_bootstrap_ndcg_difference"]={name:paired_bootstrap_difference(chrono_values,[row["metrics"][name]["ndcg@10"] for row in per_query]) for name in ("bm25","dense_minilm","rrf_bm25_dense")}
    result["bootstrap_note"]="Descriptive paired query bootstrap,10,000 resamples,95% percentile interval. Assumes independent query sampling; no multiple-comparison correction or cross-dataset generalization."
    result["model_cache_sha256"]={str(path.relative_to(Path(os.environ["CHRONOVERSE_MODEL_CACHE"]))):digest(path) for path in Path(os.environ["CHRONOVERSE_MODEL_CACHE"]).rglob("*") if path.is_file() and path.name in ("model.onnx","tokenizer.json","config.json","tokenizer_config.json","special_tokens_map.json")}
    benchmark_run.write_json(args.output, result)
    emit("complete",output=str(args.output),metrics={name:row["metrics"] for name,row in result["methods"].items()},wall_seconds=result["total_wall_seconds"])


if __name__=="__main__":
    main()
