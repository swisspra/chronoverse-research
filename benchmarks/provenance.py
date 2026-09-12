"""Git/runtime provenance and guarded benchmark artifacts; verification stays read-only."""
from __future__ import annotations
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import subprocess
from datetime import datetime, timezone
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
_REPO_RUNTIME_ALIASES = ('.benchmark-data', '.model-cache', '.runtime')


def _git(root, *args):
    try:
        return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode().rstrip('\n')
    except subprocess.CalledProcessError as exc:
        raise RuntimeError('Benchmark provenance requires an initialized git repository with a commit.') from exc


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _dirty_paths(root):
    chunks = _git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=all').split('\0')
    paths, index = set(), 0
    while index < len(chunks):
        entry = chunks[index]
        if entry:
            paths.add(entry[3:])
            if 'R' in entry[:2] or 'C' in entry[:2]:
                index += 1
                if index < len(chunks):
                    paths.add(chunks[index])
        index += 1
    return paths


def _source_files(root):
    paths = _git(root, 'ls-files', '-c', '-o', '--exclude-standard', '-z').split('\0')
    return sorted({root / p for p in paths if p and (p.endswith('.py') or Path(p).name in ('pyproject.toml','uv.lock','requirements.lock') or 'requirements' in Path(p).name) and (root / p).is_file()})


def _label(root, path):
    """Return a publishable logical path without leaking a host filesystem path."""
    root = Path(root).resolve()
    raw = Path(path)
    logical = Path(os.path.abspath(raw if raw.is_absolute() else root / raw))
    resolved = logical.resolve()
    # Resolve known runtime aliases before accepting a resolved target that may
    # itself live under this checkout (a common test/local-cache arrangement).
    for alias in _REPO_RUNTIME_ALIASES:
        link = root / alias
        if link.is_symlink():
            target = link.resolve()
            if resolved.is_relative_to(target):
                return (Path(alias) / resolved.relative_to(target)).as_posix()
    # abspath normalizes `..` without following a repo-local symlink, preserving
    # the caller's logical `.benchmark-data/...` path when it is still available.
    if logical.is_relative_to(root):
        return logical.relative_to(root).as_posix()

    if resolved.is_relative_to(root):
        return resolved.relative_to(root).as_posix()
    # Some benchmark worktrees link large ignored runtime directories to the
    # main checkout. Recover that repo-relative alias even if a caller already
    # resolved the output path before provenance capture.
    return f'<EXTERNAL>/{resolved.name}'


def run_provenance(*, repo_root=ROOT, requirements=None, predictions=None, sources=None):
    """Capture facts without writing, checking cleanliness, or running inference."""
    root = Path(repo_root).resolve()
    commit = _git(root, 'rev-parse', 'HEAD')
    freeze = '\n'.join(sorted(f"{d.metadata.get('Name', 'unknown')}=={d.version}" for d in metadata.distributions())) + '\n'
    frozen_hash = hashlib.sha256(freeze.encode()).hexdigest()
    prediction = Path(predictions).resolve() if predictions else root / 'PREDICTIONS.md'
    prediction_hash = sha256(prediction) if prediction.is_file() else None
    prediction_commit = None
    if prediction_hash and prediction.is_relative_to(root):
        relative = prediction.relative_to(root).as_posix()
        try:
            candidate = _git(root, 'log', '-1', '--format=%H', '--', relative)
            if candidate:
                committed = subprocess.check_output(['git','-C',str(root),'show',f'{candidate}:{relative}'],stderr=subprocess.PIPE)
                if hashlib.sha256(committed).hexdigest() == prediction_hash:
                    prediction_commit = candidate
        except (RuntimeError, subprocess.CalledProcessError):
            pass
    paths = [Path(p) for p in sources] if sources is not None else _source_files(root)
    dirty = sorted(_dirty_paths(root))
    return {'git_commit':commit,'git_dirty':bool(dirty),'git_dirty_paths':dirty,
            'git_describe':_git(root,'describe','--always','--tags','--dirty'),
            'python':platform.python_version(),'platform':platform.platform(),
            'started_at':datetime.now(timezone.utc).isoformat(),'load_average':list(os.getloadavg()) if hasattr(os,'getloadavg') else None,
            'requirements_sha256':sha256(requirements) if requirements else frozen_hash,
            'requirements_path':_label(root,requirements) if requirements else None,
            'package_freeze':freeze,'package_freeze_sha256':frozen_hash,
            'package_freeze_format':'importlib.metadata installed Name==Version snapshot; editable project code is covered by source_sha256',
            'source_sha256':{_label(root,p):sha256(p) for p in paths},
            'predictions_sha256':prediction_hash,'predictions_commit':prediction_commit,
            'predictions_committed_exactly':bool(prediction_commit)}


class BenchmarkRun:
    """Refuse dirty/untraceable result writes; own generated files are explicit.

    Subsequent writes may dirty only exact paths already written by this run,
    whose bytes are rechecked. Full git_dirty remains reported. Read-only users
    call run_provenance directly and are never rejected for ordinary dirty edits.
    """
    def __init__(self, *, allow_dirty=False, repo_root=ROOT, requirements=None, predictions=None, sources=None):
        self.root = Path(repo_root).resolve()
        self.options = dict(repo_root=self.root,requirements=requirements,predictions=predictions,sources=sources)
        self.allow_dirty = bool(allow_dirty)
        self.started = run_provenance(**self.options)
        self._written = {}
        if self.started['git_dirty'] and not self.allow_dirty:
            raise RuntimeError('Benchmark tree is dirty; commit changes or explicitly pass --allow-dirty before writing results.')

    def checked_provenance(self):
        current = run_provenance(**self.options)
        for field in ('git_commit','source_sha256','requirements_sha256','package_freeze_sha256','predictions_sha256','predictions_commit'):
            if current[field] != self.started[field]:
                raise RuntimeError(f'Benchmark {field} changed during the run; restart rather than publish ambiguous results.')
        for path, expected in self._written.items():
            if not path.exists() or sha256(path) != expected:
                raise RuntimeError(f'Generated benchmark output changed outside this run: {path}')
        generated = {
            label for p in self._written
            if not (label := _label(self.root,p)).startswith('<EXTERNAL>/')
        }
        unexpected = set(current['git_dirty_paths']) - generated
        if unexpected and not self.allow_dirty:
            raise RuntimeError('Benchmark tree became dirty before result write; use --allow-dirty only for an explicitly uncommitted run.')
        return {**self.started,'git_dirty':current['git_dirty'],'git_dirty_paths':current['git_dirty_paths'],
                'git_describe_at_write':current['git_describe'],'checked_at':current['started_at'],
                'load_average_at_write':current['load_average'],'allow_dirty':self.allow_dirty,
                'generated_outputs':sorted(_label(self.root,p) for p in self._written),
                'generated_outputs_dirty_exemption':bool(set(current['git_dirty_paths']) & generated)}

    def write_bytes(self, path, content):
        """Guard verbatim JSONL/binary bytes and return a receipt for a manifest.

        Provenance is returned separately; no header is injected into the file.
        Later writes recheck this exact generated path just like JSON artifacts.
        """
        if not isinstance(content, bytes):
            raise TypeError('write_bytes requires bytes')
        path = Path(path).resolve()
        provenance = self.checked_provenance()
        provenance['generated_outputs'] = sorted(set(provenance['generated_outputs']) | {_label(self.root,path)})
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary = path.with_name(f'.{path.name}.{uuid4().hex}.tmp')
        try:
            temporary.write_bytes(content)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        self._written[path] = sha256(path)
        return {'sha256':self._written[path],'provenance':provenance}

    def write_json(self, path, payload):
        logical_path = Path(path)
        path = logical_path.resolve()
        provenance = self.checked_provenance()
        provenance["generated_outputs"] = sorted(
            set(provenance["generated_outputs"]) | {_label(self.root,logical_path)}
        )
        value = {**payload, 'provenance':provenance} if isinstance(payload,dict) else {'results':payload,'provenance':provenance}
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary = path.with_name(f'.{path.name}.{uuid4().hex}.tmp')
        try:
            temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        self._written[path] = sha256(path)
        return value


def add_provenance_argument(parser):
    parser.add_argument('--allow-dirty',action='store_true',help='Explicitly record an uncommitted benchmark run; source changes during the run still fail.')
    return parser
