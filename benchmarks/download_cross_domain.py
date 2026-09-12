"""Fetch the three fixed BEIR archives with checksum verification."""
from pathlib import Path
import argparse
import os
import urllib.request
import zipfile

from benchmarks.cross_domain import DATASETS, DATA_DIR, hash_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--datasets', default='scifact,nfcorpus,fiqa')
    args = parser.parse_args()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in args.datasets.split(','):
        name = name.strip()
        spec = DATASETS[name]
        archive = DATA_DIR / f'{name}.zip'
        if not archive.exists():
            temporary = archive.with_suffix('.zip.download')
            try:
                urllib.request.urlretrieve(spec['archive_url'], temporary)
                if hash_file(temporary) != spec['sha256']:
                    raise ValueError(f'{name}: downloaded archive SHA-256 mismatch')
                os.replace(temporary, archive)
            finally:
                temporary.unlink(missing_ok=True)
        if hash_file(archive) != spec['sha256'] or hash_file(archive, 'md5') != spec['md5']:
            raise ValueError(f'{name}: archive checksum mismatch')
        destination = DATA_DIR / name
        required = [destination / name / p for p in ('corpus.jsonl', 'queries.jsonl', 'qrels/test.tsv')]
        if not all(p.is_file() for p in required):
            destination.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive) as source:
                for member in source.infolist():
                    resolved = (destination / member.filename).resolve()
                    if not resolved.is_relative_to(destination.resolve()):
                        raise ValueError(f'{name}: unsafe archive path')
                source.extractall(destination)
        assert all(p.is_file() for p in required)
        print(f'{name}: verified archive and corpus/query/qrel files', flush=True)


if __name__ == '__main__':
    main()
