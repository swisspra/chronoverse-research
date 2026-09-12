from pathlib import Path
import json
import subprocess
import pytest


def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args],text=True).strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path,'init','-q')
    git(tmp_path,'config','user.email','test@example.invalid')
    git(tmp_path,'config','user.name','Test')
    (tmp_path/'runner.py').write_text('value = 1\n')
    (tmp_path/'PREDICTIONS.md').write_text('Frozen hypothesis\n')
    git(tmp_path,'add','.')
    git(tmp_path,'commit','-qm','fixture')
    return tmp_path


def test_capture_is_read_only_and_records_committed_prediction(repo):
    from benchmarks.provenance import run_provenance
    before=git(repo,'status','--porcelain')
    p=run_provenance(repo_root=repo,predictions=repo/'PREDICTIONS.md')
    assert p['git_commit']==git(repo,'rev-parse','HEAD')
    assert p['git_dirty'] is False and len(p['requirements_sha256'])==64
    assert p['predictions_commit']==p['git_commit'] and len(p['predictions_sha256'])==64
    assert p['source_sha256']['runner.py']
    assert git(repo,'status','--porcelain')==before


def test_dirty_start_refuses_before_writing_and_override_is_explicit(repo):
    from benchmarks.provenance import BenchmarkRun
    (repo/'runner.py').write_text('value = 2\n')
    with pytest.raises(RuntimeError,match='dirty'):
        BenchmarkRun(repo_root=repo)
    target=repo/'result.json'
    assert not target.exists()
    run=BenchmarkRun(repo_root=repo,allow_dirty=True)
    run.write_json(target,{'value':2})
    assert json.loads(target.read_text())['provenance']['allow_dirty'] is True
    assert json.loads(target.read_text())['provenance']['git_dirty'] is True


def test_recheck_catches_midrun_changes_even_with_dirty_override(repo):
    from benchmarks.provenance import BenchmarkRun
    run=BenchmarkRun(repo_root=repo,allow_dirty=True)
    (repo/'runner.py').write_text('value = 999\n')
    with pytest.raises(RuntimeError,match='changed'):
        run.write_json(repo/'result.json',{})
    assert not (repo/'result.json').exists()


def test_read_only_capture_accepts_dirty_tree(repo):
    from benchmarks.provenance import run_provenance
    (repo/'runner.py').write_text('value = 2\n')
    assert run_provenance(repo_root=repo)['git_dirty'] is True


def test_uncommitted_prediction_cannot_claim_historical_commit(repo):
    from benchmarks.provenance import run_provenance
    (repo/'PREDICTIONS.md').write_text('Changed after seeing test results\n')
    p=run_provenance(repo_root=repo,predictions=repo/'PREDICTIONS.md')
    assert p['predictions_commit'] is None
    assert p['predictions_committed_exactly'] is False


def test_multiple_managed_artifacts_and_unrelated_dirty_recheck(repo):
    from benchmarks.provenance import BenchmarkRun
    run=BenchmarkRun(repo_root=repo)
    run.write_json(repo/'results'/'one.json',{'x':1})
    run.write_json(repo/'results'/'two.json',{'x':2})
    assert json.loads((repo/'results'/'two.json').read_text())['provenance']['git_dirty'] is True
    (repo/'unrelated.txt').write_text('Not this run')
    with pytest.raises(RuntimeError,match='dirty'):
        run.write_json(repo/'results'/'three.json',{})


def test_managed_tracked_output_path_is_not_truncated(repo):
    from benchmarks.provenance import BenchmarkRun
    path=repo/'result.json'
    path.write_text('{}\n')
    git(repo,'add','result.json');git(repo,'commit','-qm','empty result')
    run=BenchmarkRun(repo_root=repo)
    run.write_json(path,{'x':1})
    run.write_json(path,{'x':2})
    assert json.loads(path.read_text())['provenance']['git_dirty_paths']==['result.json']


def test_actual_runner_cli_guard_and_wrapped_rankings(repo):
    import shutil
    import sys
    project = Path(__file__).resolve().parents[2]
    package = repo/'benchmarks'
    package.mkdir()
    (package/'__init__.py').write_text('')
    for name in ('provenance.py','failure_cases.py'):
        shutil.copyfile(project/'benchmarks'/name,package/name)
    public=repo/'.benchmark-data'/'scifact';public.mkdir(parents=True)
    (public/'queries.jsonl').write_text(json.dumps({'_id':'1','text':'query'})+'\n')
    (public/'corpus.jsonl').write_text(json.dumps({'_id':'D','title':'Document'})+'\n')
    out=repo/'docs'/'benchmarks';out.mkdir(parents=True)
    names=('bm25','dense_minilm','rrf_bm25_dense','chronoverse_store_optimized_cache')
    (out/'scifact-results.json').write_text(json.dumps({'per_query':[{'query_id':'1','metrics':{n:{'ndcg@10':.5} for n in names}}]}))
    for name in names:
        (out/f'scifact-{name}.run.json').write_text(json.dumps({'rankings':{'1':['D']},'provenance':{'historical':False}}))
    data=package/'data';data.mkdir()
    (data/'temporal-v1.json').write_text(json.dumps({'assertions':[],'queries':[{'id':'q','category':'retraction_empty'}]}))
    (out/'temporal-results.json').write_text(json.dumps({'systems':{'Chronoverse stock':{'rankings':{'q':[]}}}}))
    git(repo,'add','.');git(repo,'commit','-qm','runner fixture')
    (repo/'unrelated.txt').write_text('dirty')
    command=[sys.executable,'-m','benchmarks.failure_cases']
    denied=subprocess.run(command,cwd=repo,text=True,capture_output=True)
    assert denied.returncode and 'dirty' in denied.stderr
    assert not (out/'failure-cases.json').exists()
    allowed=subprocess.run(command+['--allow-dirty'],cwd=repo,text=True,capture_output=True)
    assert allowed.returncode==0,allowed.stderr
    value=json.loads((out/'failure-cases.json').read_text())
    assert value['provenance']['allow_dirty'] and value['provenance']['git_dirty']
    assert value['scifact'][0]['rankings']['bm25']==[{'id':'D','title':'Document'}]


def test_label_preserves_repo_symlink_alias_and_redacts_true_external(repo, tmp_path):
    from benchmarks.provenance import _label
    external = tmp_path/'large-cache'
    external.mkdir()
    (repo/'.benchmark-data').symlink_to(external, target_is_directory=True)
    result = external/'result.json'
    result.write_text('{}')
    assert _label(repo, repo/'.benchmark-data'/'result.json') == '.benchmark-data/result.json'
    assert _label(repo, result.resolve()) == '.benchmark-data/result.json'
    elsewhere = tmp_path.parent/f'{tmp_path.name}-private'/'same.json'
    elsewhere.parent.mkdir()
    elsewhere.write_text('{}')
    assert _label(repo, elsewhere) == '<EXTERNAL>/same.json'


def test_label_resolves_relative_to_repo_and_normalizes_parent_escape(repo, monkeypatch, tmp_path):
    from benchmarks.provenance import _label
    other_cwd = tmp_path.parent / f'{tmp_path.name}-cwd'
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    assert _label(repo, 'runner.py') == 'runner.py'
    assert _label(repo, Path('..') / 'secret.json') == '<EXTERNAL>/secret.json'


def test_guarded_bytes_preserves_jsonl_and_registers_exact_output(repo):
    from benchmarks.provenance import BenchmarkRun
    run=BenchmarkRun(repo_root=repo)
    content=b'{"id":1}\n{"id":2}\n'
    target=repo/'manifest.jsonl'
    receipt=run.write_bytes(target,content)
    assert target.read_bytes()==content
    assert len(receipt['sha256'])==64
    run.write_json(repo/'metadata.json',receipt)
    assert 'manifest.jsonl' in receipt['provenance']['generated_outputs']
    target.write_bytes(b'changed')
    with pytest.raises(RuntimeError,match='outside'):
        run.write_json(repo/'later.json',{})


def test_guarded_bytes_rechecks_source_before_write(repo):
    from benchmarks.provenance import BenchmarkRun
    run=BenchmarkRun(repo_root=repo,allow_dirty=True)
    (repo/'runner.py').write_text('changed = True\n')
    with pytest.raises(RuntimeError,match='changed'):
        run.write_bytes(repo/'manifest.jsonl',b'{}\n')
    assert not (repo/'manifest.jsonl').exists()
