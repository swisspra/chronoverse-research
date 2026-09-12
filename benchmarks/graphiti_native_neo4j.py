"""Manage one workspace-local Neo4j 5.26.2 process for native Graphiti tests."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tarfile
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
VERSION = '5.26.2'
ARCHIVE_NAME = f'neo4j-community-{VERSION}-unix.tar.gz'
ARCHIVE_URL = f'https://dist.neo4j.org/{ARCHIVE_NAME}'
ARCHIVE_SHA256 = '95dde4f8092b9dffb57f74248ef6579bc36d6418c07ba7c513d9c95a36f44518'
RUNTIME = ROOT / '.runtime/graphiti-neo4j'
DOWNLOAD = ROOT / '.runtime/downloads' / ARCHIVE_NAME
HOME = RUNTIME / f'neo4j-community-{VERSION}'
PASSWORD_FILE = RUNTIME / 'password'
JAVA_HOME = ROOT / '.runtime/tools/java/Contents/Home'
HTTP_PORT = 17474
BOLT_PORT = 17687
MARKER = '# CHRONOVERSE GRAPHITI NATIVE ISOLATED CONFIG'


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config_block() -> str:
    return f'''\n{MARKER}
dbms.usage_report.enabled=false
server.default_listen_address=127.0.0.1
server.default_advertised_address=127.0.0.1
server.bolt.listen_address=127.0.0.1:{BOLT_PORT}
server.bolt.advertised_address=127.0.0.1:{BOLT_PORT}
server.http.listen_address=127.0.0.1:{HTTP_PORT}
server.http.advertised_address=127.0.0.1:{HTTP_PORT}
server.memory.heap.initial_size=512m
server.memory.heap.max_size=1g
server.memory.pagecache.size=512m
'''


def _environment() -> dict[str, str]:
    env = dict(os.environ)
    env['JAVA_HOME'] = str(JAVA_HOME)
    env['PATH'] = f'{JAVA_HOME / "bin"}{os.pathsep}{env.get("PATH", "")}'
    env['NEO4J_HOME'] = str(HOME)
    return env


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(HOME / 'bin' / args[0]), *args[1:]],
        env=_environment(),
        text=True,
        capture_output=True,
        check=check,
        timeout=120,
    )


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.2):
            return True
    except OSError:
        return False


def prepare() -> None:
    """Download, verify, extract, and configure without starting a service."""

    if not JAVA_HOME.joinpath('bin/java').is_file():
        raise RuntimeError(f'workspace Java 21 not found under {JAVA_HOME}')
    DOWNLOAD.parent.mkdir(parents=True, exist_ok=True)
    if not DOWNLOAD.is_file():
        temporary = DOWNLOAD.with_suffix('.partial')
        urllib.request.urlretrieve(ARCHIVE_URL, temporary)
        temporary.replace(DOWNLOAD)
    actual = sha256(DOWNLOAD)
    if actual != ARCHIVE_SHA256:
        raise RuntimeError(f'Neo4j archive SHA-256 mismatch: {actual}')
    if not HOME.is_dir():
        RUNTIME.mkdir(parents=True, exist_ok=True)
        with tarfile.open(DOWNLOAD, 'r:gz') as archive:
            archive.extractall(RUNTIME, filter='data')

    config = HOME / 'conf/neo4j.conf'
    text = config.read_text()
    if MARKER in text:
        text = text.split(MARKER, 1)[0].rstrip() + '\n'
    config.write_text(text + config_block())

    PASSWORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not PASSWORD_FILE.exists():
        PASSWORD_FILE.write_text(secrets.token_urlsafe(32) + '\n')
        PASSWORD_FILE.chmod(0o600)
    auth_store = HOME / 'data/dbms/auth'
    if not auth_store.exists():
        password = PASSWORD_FILE.read_text().strip()
        _run('neo4j-admin', 'dbms', 'set-initial-password', password)


def start() -> None:
    prepare()
    status = _run('neo4j', 'status', check=False)
    if status.returncode == 0:
        print('workspace Neo4j already running')
        return
    occupied = [port for port in (HTTP_PORT, BOLT_PORT) if _port_open(port)]
    if occupied:
        raise RuntimeError(f'refusing to start: dedicated port already occupied: {occupied}')
    result = _run('neo4j', 'start')
    if result.stdout:
        print(result.stdout.strip())


def stop() -> None:
    if not HOME.is_dir():
        print('workspace Neo4j is not prepared')
        return
    result = _run('neo4j', 'stop', check=False)
    if result.returncode not in {0, 3}:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    print((result.stdout or 'workspace Neo4j stopped').strip())


def status() -> None:
    if not HOME.is_dir():
        print('workspace Neo4j is not prepared')
        return
    result = _run('neo4j', 'status', check=False)
    print((result.stdout or result.stderr).strip())
    print(f'http_open={_port_open(HTTP_PORT)} bolt_open={_port_open(BOLT_PORT)}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'start', 'stop', 'status'))
    args = parser.parse_args()
    globals()[args.command]()


if __name__ == '__main__':
    main()
