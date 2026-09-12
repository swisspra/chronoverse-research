#!/usr/bin/env python3
"""Build and run the complete local product. Ctrl-C stops only owned processes."""
import argparse
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def run(command, **kwargs):
    subprocess.run(command, cwd=ROOT, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--lexical', action='store_true', help='Skip model weights and use labeled hashed lexical vectors')
    parser.add_argument('--no-build', action='store_true', help='Use existing frontend build and Python environment')
    args = parser.parse_args()
    for port in (8000, 8001):
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                sys.exit(f'Port {port} is already in use. Stop that process before launching Chronoverse.')
    if not args.no_build:
        command = ['uv', 'sync', '--project', 'backend', '--python', '3.12', '--group', 'dev']
        if not args.lexical:
            command.extend(['--extra', 'semantic'])
        run(command)
        run(['npm', 'ci', '--prefix', 'frontend'])
        run(['npm', 'run', 'build', '--prefix', 'frontend'])
    python = ROOT / 'backend' / '.venv' / 'bin' / 'python'
    if not python.exists() or not (ROOT / 'frontend' / 'dist' / 'index.html').exists():
        sys.exit('Missing build/environment. Run without --no-build first.')
    environment = dict(os.environ)
    environment['CHRONOVERSE_DB'] = str(ROOT / 'data' / 'chronoverse.sqlite3')
    environment['CHRONOVERSE_MODEL_CACHE'] = str(ROOT / '.model-cache')
    environment['CHRONOVERSE_EMBEDDINGS'] = 'lexical' if args.lexical else 'semantic'
    environment['PYTHONUNBUFFERED'] = '1'
    if not args.lexical and not args.no_build:
        run([str(python), 'scripts/download_model.py'], env=environment)
    logdir = ROOT / '.runtime'
    logdir.mkdir(exist_ok=True)
    processes = []
    logs = []
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        for name, command in [
            ('api', [str(python), '-m', 'uvicorn', 'chronoverse.api:app', '--host', '127.0.0.1', '--port', '8000']),
            ('mcp', [str(python), '-m', 'chronoverse.mcp_server', '--transport', 'streamable-http', '--port', '8001']),
        ]:
            if name == 'mcp':
                for _ in range(100):
                    if processes[0].poll() is not None:
                        raise RuntimeError('API exited during startup; read .runtime/api.log')
                    try:
                        urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=1).close()
                        break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError('API health check timed out; read .runtime/api.log')
            log = (logdir / f'{name}.log').open('w')
            logs.append(log)
            processes.append(subprocess.Popen(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT))
        print('Chronoverse: http://127.0.0.1:8000\nMCP: http://127.0.0.1:8001/mcp\nCtrl-C stops both. Logs: .runtime/', flush=True)
        while True:
            for process in processes:
                if process.poll() is not None:
                    raise RuntimeError(f'Service exited with code {process.returncode}; read .runtime/ logs')
            time.sleep(1)
    except KeyboardInterrupt:
        print('\nStopping Chronoverse.', flush=True)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log in logs:
            log.close()


if __name__ == '__main__':
    main()
