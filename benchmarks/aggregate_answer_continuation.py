"""Offline metadata wrapper around unchanged, frozen answer statistics.

Run only after all continuation slots finish. No inference or provider calls.
"""
from __future__ import annotations
import argparse
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from benchmarks.provenance import BenchmarkRun
from benchmarks.verify_answer_continuation import verify_bindings,verify_union
from benchmarks.verify_answer_pilot import sha,require,MODEL

FROZEN_COMMIT='b8b3fc3e115203ec701f59e3a14c1b3058ac7060'
FROZEN_SOURCES={
    'benchmarks/answer_statistics.py':'2ab460e84e15de1688099bb2b2897f928e28e52165d1ca9e9e206cbca960fd36',
    'benchmarks/answer_experiment.py':'ac3e33c3cc52f6f87d48dd5baea39eb9de30f03db65e32f315ba24e4b2f0decd'}


def check_frozen_sources(root):
    require(all((root/p).is_file() and sha((root/p).read_bytes())==expected for p,expected in FROZEN_SOURCES.items()),'Frozen statistics/scorer source mismatch.')


def label_summary(summary):
    require(summary.get('planned_queries')==50 and summary.get('planned_requests')==summary.get('recorded_requests')==750,'Not all750 original slots are recorded.')
    return {**summary,'status':'completed_plan_with_uncertainty','execution_status':'completed_plan_with_uncertainty',
        'aggregation_coverage_status':'all_750_planned_slots_recorded',
        'interpretation':'749 terminal responses and one preserved unknown outcome; truncated/uncertain attempts remain failures in frozen accuracy denominators.'}


FROZEN_CALL="""
import gzip,json,sys
from pathlib import Path
from benchmarks.answer_statistics import summarize,validate_binding
manifest,result,prompt,output,model=sys.argv[1:]
raw=Path(manifest).read_bytes();raw=gzip.decompress(raw) if manifest.endswith('.gz') else raw
rr=Path(result).read_bytes();rr=gzip.decompress(rr) if result.endswith('.gz') else rr
rows=[json.loads(line) for line in raw.decode().splitlines() if line.strip()];data=json.loads(rr)
validate_binding(raw,rows,data,Path(prompt).read_bytes())
Path(output).write_text(json.dumps(summarize(rows,data['requests'],model),allow_nan=False))
"""


def frozen_summary(frozen_root,paths):
    check_frozen_sources(frozen_root)
    head=subprocess.check_output(['git','-C',str(frozen_root),'rev-parse','HEAD'],text=True).strip()
    require(head==FROZEN_COMMIT,'Frozen statistics worktree commit mismatch.')
    with tempfile.TemporaryDirectory(prefix='chronoverse-answer-summary-') as directory:
        output=Path(directory)/'summary.json';env={**os.environ};env.pop('PYTHONPATH',None)
        subprocess.run([sys.executable,'-c',FROZEN_CALL,*[str(paths[k].resolve()) for k in ('manifest','union','prompt')],str(output),MODEL],
            cwd=frozen_root,env=env,check=True,capture_output=True,text=True)
        summary=json.loads(output.read_text())
    check_frozen_sources(frozen_root)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('manifest','prompt','original','continuation','union','frozen-root','output'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();paths={k:getattr(args,k) for k in ('manifest','prompt','original','continuation','union')}
    require(not args.output.exists() and args.output.resolve() not in {p.resolve() for p in paths.values()},'Refuse existing/input output path.')
    run=BenchmarkRun();stored={k:p.read_bytes() for k,p in paths.items()}
    raw={k:gzip.decompress(value) if paths[k].suffix=='.gz' else value for k,value in stored.items()}
    continuation,union=verify_bindings(raw)
    audit=verify_union(raw['manifest'],raw['prompt'],raw['original'],continuation,union)
    summary=label_summary(frozen_summary(args.frozen_root,paths))
    require(all(p.read_bytes()==stored[k] for k,p in paths.items()),'Aggregation inputs changed.')
    summary.update(frozen_statistics_commit=FROZEN_COMMIT,frozen_source_sha256=FROZEN_SOURCES,
        file_sha256={k:sha(v) for k,v in stored.items()},raw_sha256={k:sha(v) for k,v in raw.items()},
        result_file_sha256=sha(stored['union']),manifest_file_sha256=sha(stored['manifest']),
        manifest_binding={'manifest_sha256':sha(raw['manifest']),'prompt_sha256':sha(raw['prompt'])},
        transport_and_format_audit=audit,
        wrapper_note='Metadata and integrity wrapper only; frozen summarize and score_answer outputs are unchanged.',
        supplemental_metric_labels={'strict_support_complete':'Raw exact gold-ID inclusion among valid answerable completions; no visibility/context/stale eligibility filtering.'})
    run.write_json(args.output,summary)
    print(json.dumps({'status':summary['status'],'aggregation_coverage_status':summary['aggregation_coverage_status'],'output':str(args.output)}))


if __name__=='__main__':main()
