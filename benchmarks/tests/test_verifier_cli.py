"""Corrupt a copy; verifier CLI must fail without touching historical artifacts."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def test_v2_cli_rejects_corrupted_copy_without_writing(tmp_path):
    source=ROOT/'docs/benchmarks-v2/index-results.json'
    original=hashlib.sha256(source.read_bytes()).hexdigest()
    result=json.loads(source.read_text())
    result['phases']['fresh']['metrics']['ndcg@10'] += .01
    (tmp_path/'index-results.json').write_text(json.dumps(result))
    completed=subprocess.run([sys.executable,'-m','benchmarks.verify_v2_artifacts','--input-dir',str(tmp_path)],cwd=ROOT,capture_output=True,text=True)
    assert completed.returncode!=0
    assert 'ndcg@10' in completed.stderr, completed.stderr
    assert hashlib.sha256(source.read_bytes()).hexdigest()==original
    assert not (tmp_path/'verification-results.json').exists()


def test_v2_cli_default_verification_is_read_only():
    receipt=ROOT/'docs/benchmarks-v2/verification-results.json'
    before=(receipt.stat().st_mtime_ns,hashlib.sha256(receipt.read_bytes()).hexdigest())
    completed=subprocess.run([sys.executable,'-m','benchmarks.verify_v2_artifacts','--input-dir',str(ROOT/'docs/benchmarks-v2'),'--data-dir',str(ROOT/'.benchmark-data')],cwd=ROOT,capture_output=True,text=True)
    assert completed.returncode==0, completed.stderr
    assert json.loads(completed.stdout)['status']=='passed'
    assert (receipt.stat().st_mtime_ns,hashlib.sha256(receipt.read_bytes()).hexdigest())==before
