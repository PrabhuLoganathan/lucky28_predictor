#!/usr/bin/env python3
"""Start Django and the Lucky Number logger from this repository."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import signal
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import venv

ROOT = Path(__file__).resolve().parent
VENV = ROOT / '.venv'
LOGGER = ROOT / 'chamet_logger_standalone'
LOCAL = ROOT / '.local'


def run(command, **kwargs):
    subprocess.run([str(part) for part in command], cwd=ROOT, check=True, **kwargs)


def prepare(check_only):
    python = VENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        if check_only:
            raise RuntimeError('Missing .venv. Run python3 run.py --setup.')
        print('Creating the shared Python environment...', flush=True)
        venv.EnvBuilder(with_pip=True).create(VENV)
    if Path(sys.prefix).resolve() != VENV.resolve():
        os.execv(str(python), [str(python), str(ROOT / 'run.py'), *sys.argv[1:]])
    modules = ['django', 'rest_framework', 'pandas', 'twilio', 'dotenv', 'requests']
    if any(importlib.util.find_spec(name) is None for name in modules):
        if check_only:
            raise RuntimeError('Python dependencies are missing. Run python3 run.py --setup.')
        run([python, '-m', 'pip', 'install', '--cache-dir', LOCAL / 'pip-cache', '-r', ROOT / 'requirements.txt'])
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    if not shutil.which('node') or not shutil.which('npm'):
        raise RuntimeError('Install Node.js 22 or newer (including npm), then run this command again.')
    version = subprocess.check_output(['node', '-p', 'process.versions.node'], text=True).strip()
    if int(version.split('.')[0]) < 22:
        raise RuntimeError('Node.js 22 or newer is required.')
    if not all((LOGGER / 'node_modules' / name / 'package.json').exists()
               for name in ('typescript', '@playwright/test', '@types/node')):
        if check_only:
            raise RuntimeError('Logger dependencies are missing. Run python3 run.py --setup.')
        run(['npm', '--prefix', LOGGER, 'ci', '--cache', LOCAL / 'npm-cache'])
    token_path = LOCAL / 'logger-token'
    if not os.environ.get('LUCKY28_LOGGER_TOKEN') and not token_path.exists():
        if check_only:
            raise RuntimeError('Shared logger token is missing. Run python3 run.py --setup.')
        LOCAL.mkdir(exist_ok=True)
        with os.fdopen(os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as handle:
            handle.write(secrets.token_urlsafe(32) + '\n')
    if not check_only:
        run(['npm', '--prefix', LOGGER, 'run', 'build'])
    run([python, ROOT / 'django_lucky28/manage.py', 'check'])
    return python


def health(api_url, token):
    request = urllib.request.Request(f'{api_url}/health/', headers={'X-Lucky28-Token': token})
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            data = json.load(response)
            return data.get('service') == 'lucky28' and data.get('schema_version') == 1
    except (OSError, ValueError):
        return False


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main():
    def interrupted(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', action='store_true', help='Install dependencies and prepare the database, then exit.')
    parser.add_argument('--check', action='store_true', help='Check dependencies, configuration, and API connectivity.')
    parser.add_argument('--django-only', action='store_true', help='Run the dashboard without opening Chamet.')
    parser.add_argument('--replay', type=Path, help='Send a captured JSONL file to Django without opening a browser.')
    parser.add_argument('--host')
    parser.add_argument('--port', type=int)
    args = parser.parse_args()
    python = prepare(args.check)
    host = args.host or os.environ.get('LUCKY28_HOST', '127.0.0.1')
    port = args.port or int(os.environ.get('LUCKY28_PORT', '8000'))
    api_url = os.environ.get('LUCKY28_API_URL', f'http://{host}:{port}/api/logger').rstrip('/')
    os.environ.update(LUCKY28_HOST=host, LUCKY28_PORT=str(port), LUCKY28_API_URL=api_url)
    token = os.environ.get('LUCKY28_LOGGER_TOKEN') or (LOCAL / 'logger-token').read_text().strip()
    if args.check:
        if not health(api_url, token):
            raise RuntimeError('Dependencies are ready; Django is stopped or its logger URL/token differs. Run python3 run.py.')
        print('Ready: shared Python environment, Node.js, and authenticated Lucky28 API.')
        return
    run([python, ROOT / 'django_lucky28/manage.py', 'migrate', '--noinput'])
    if args.setup:
        print('Setup complete. Start both services with: python3 run.py')
        return
    django = logger = None
    try:
        if not health(api_url, token):
            try:
                connection = socket.create_connection((host, port), timeout=1)
            except OSError:
                connection = None
            if connection:
                connection.close()
                raise RuntimeError(f'Port {port} is already occupied by a server with a different logger API/token. Restart that Django server or choose --port.')
            django = subprocess.Popen([str(python), str(ROOT / 'django_lucky28/manage.py'), 'runserver', f'{host}:{port}', '--noreload'], cwd=ROOT)
            for _ in range(100):
                if django.poll() is not None:
                    raise RuntimeError('Django exited before it was ready.')
                if health(api_url, token):
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError('Django did not become ready. Check LUCKY28_API_URL and the server output.')
        print(f'Dashboard: http://{host}:{port}/', flush=True)
        if args.django_only:
            if django:
                django.wait()
            return
        command = ['node', str(LOGGER / 'dist/main.js')]
        if args.replay:
            command += ['--replay', str(args.replay.resolve())]
        logger = subprocess.Popen(command, cwd=ROOT)
        while logger.poll() is None:
            if django and django.poll() is not None:
                raise RuntimeError('Django stopped unexpectedly. Restart with python3 run.py.')
            time.sleep(0.25)
        code = logger.returncode
        if code:
            raise RuntimeError(f'Logger exited with status {code}. Captured pending events remain on disk.')
    except KeyboardInterrupt:
        print('\nStopping the logger and the Django process started by this command...')
    finally:
        stop(logger)
        stop(django)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
