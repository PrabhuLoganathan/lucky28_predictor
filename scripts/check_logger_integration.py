"""Verify browser capture -> Django -> signal feedback using only local fixtures."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def free_port():
    with socket.socket() as connection:
        connection.bind(('127.0.0.1', 0))
        return connection.getsockname()[1]


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        packets = [
            {'info': {'gameNo': 'fixture-1', 'winResult': -1, 'status': 1, 'surplusSeconds': 10,
                      'numberTypeRates': [{'numberType': 'B', 'proportion': 0.6}]}},
            {'page': 'IM', 'params': json.dumps({'code': 651, 'info': {
                'gameNo': 'fixture-1', 'winResult': 14, 'status': 3, 'surplusSeconds': 0}})},
            {'info': {'gameNo': 'fixture-2', 'winResult': -1, 'status': 1, 'surplusSeconds': 5}},
            {'info': {'gameNo': 'fixture-2', 'winResult': 16, 'status': 3, 'surplusSeconds': 0}},
            {'info': {'gameNo': 'race-ignore', 'winResult': 19, 'winCarId': 1, 'status': 3, 'surplusSeconds': 0}},
        ]
        page = '<!doctype html><title>Lucky Number local fixture</title><h1>Local integration check</h1><script>'
        page += f'const packets = {json.dumps(packets)};'
        page += 'packets.forEach((packet, i) => setTimeout(() => console.log(packet), 500 + i * 400));</script>'
        body = page.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main():
    port = free_port()
    fixture = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    backend = logger = None
    try:
        with tempfile.TemporaryDirectory(prefix='lucky28-integration-') as folder:
            folder = Path(folder)
            env = dict(os.environ, LUCKY28_DB_PATH=str(folder / 'check.db'),
                       LUCKY28_LOGGER_TOKEN='local-integration-test-token',
                       LUCKY28_API_URL=f'http://127.0.0.1:{port}/api/logger',
                       CHAMET_PROFILE_DIR=str(folder / 'browser'), CHAMET_DATA_DIR=str(folder / 'events'),
                       CHAMET_GAME_URL=f'http://127.0.0.1:{fixture.server_port}',
                       CHAMET_HEADLESS='true', CHAMET_BROWSER_CHANNEL='chrome')
            with (folder / 'backend.log').open('w+') as server_log, (folder / 'logger.log').open('w+') as logger_log:
                try:
                    backend = subprocess.Popen([str(PYTHON), str(ROOT / 'run.py'), '--django-only', '--port', str(port)],
                                               cwd=ROOT, env=env, stdout=server_log, stderr=subprocess.STDOUT)
                    for _ in range(150):
                        if backend.poll() is not None:
                            raise RuntimeError('Test backend stopped during startup.')
                        try:
                            request = urllib.request.Request(env['LUCKY28_API_URL'] + '/health/',
                                                             headers={'X-Lucky28-Token': env['LUCKY28_LOGGER_TOKEN']})
                            with urllib.request.urlopen(request, timeout=1) as response:
                                if response.status == 200:
                                    break
                        except OSError:
                            time.sleep(0.2)
                    else:
                        raise RuntimeError('Timed out waiting for the temporary Django server.')
                    subprocess.run([str(PYTHON), str(ROOT / 'django_lucky28/manage.py'), 'shell', '-c',
                                    "from games.models import SignalRule; SignalRule.objects.create(name='Two Big', rule_type='STREAK', dimension='BIG_SMALL', target_value='Big', threshold=2)"],
                                   cwd=ROOT, env=env, check=True, stdout=server_log, stderr=subprocess.STDOUT)
                    logger = subprocess.Popen(['node', str(ROOT / 'chamet_logger_standalone/dist/main.js')],
                                              cwd=ROOT, env=env, stdout=logger_log, stderr=subprocess.STDOUT)
                    signal_file = folder / 'events/signals.jsonl'
                    for _ in range(120):
                        if logger.poll() is not None:
                            raise RuntimeError('The browser logger stopped unexpectedly.')
                        if signal_file.exists():
                            break
                        time.sleep(0.25)
                    else:
                        raise RuntimeError('No signal feedback was received from the browser fixture.')
                    with sqlite3.connect(folder / 'check.db') as connection:
                        games = connection.execute('SELECT game_no, has_pre, has_winner, winning_number, winner_event_ts FROM games_gameround ORDER BY game_no').fetchall()
                        assert len(games) == 2, games
                        assert all(game[1:3] == (1, 1) and game[4] for game in games), games
                        assert [game[3] for game in games] == [14, 16], games
                        assert connection.execute('SELECT COUNT(*) FROM games_signallog').fetchone()[0] == 1
                    feedback = [json.loads(line) for line in signal_file.read_text().splitlines()]
                    assert len(feedback) == 1 and feedback[0]['signal']['rule__name'] == 'Two Big', feedback
                    assert not list((folder / 'events/pending').glob('*.json'))
                    print('PASS: browser console/IM packets -> authenticated Django API -> UTC games -> signal feedback.')
                    print('PASS: Lucky Race packet ignored; real Chamet and the live database were not used.')
                except Exception:
                    for log in (server_log, logger_log):
                        log.flush()
                        log.seek(0)
                        print(log.read()[-6000:], file=sys.stderr)
                    raise
                finally:
                    stop(logger)
                    stop(backend)
            with socket.socket() as connection:
                assert connection.connect_ex(('127.0.0.1', port)) != 0, 'Temporary Django process was not stopped.'
            print('PASS: startup and shutdown leave no temporary Django listener running.')
    finally:
        fixture.shutdown()
        fixture.server_close()


if __name__ == '__main__':
    main()
