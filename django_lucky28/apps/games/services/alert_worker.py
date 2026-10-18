"""Start the fixed worker command; stopping is cooperative, never an arbitrary PID kill."""
from pathlib import Path
import os
import subprocess
import sys
import threading

from django.conf import settings
from django.utils import timezone
from games.models import AlertRuntime


def worker_running(runtime=None):
    runtime = runtime or AlertRuntime.objects.filter(pk=1).first()
    return bool(runtime and runtime.worker_status in ('running', 'starting') and runtime.heartbeat_at
                and (timezone.now() - runtime.heartbeat_at).total_seconds() < 90)


def start_worker():
    import fcntl
    directory = Path(settings.ALERT_STATE_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'launch.lock').open('a') as launch:
        fcntl.flock(launch, fcntl.LOCK_EX)
        runtime, _ = AlertRuntime.objects.get_or_create(pk=1)
        if worker_running(runtime):
            return False
        with (directory / 'worker.lock').open('a') as lease:
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
        AlertRuntime.objects.filter(pk=1).update(stop_requested=False, worker_status='starting', heartbeat_at=timezone.now())
        environment = os.environ.copy()
        environment['LUCKY28_DB_PATH'] = str(settings.DATABASES['default']['NAME'])
        environment['ALERT_STATE_DIR'] = str(directory)
        try:
            with (directory / 'worker.log').open('ab') as log:
                process = subprocess.Popen(
                    [sys.executable, str(settings.BASE_DIR / 'manage.py'), 'run_alert_messaging', '--managed'],
                    cwd=settings.PROJECT_ROOT, env=environment, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=log, start_new_session=True,
                )
            # Reap a finished child without holding up the web request.
            threading.Thread(target=process.wait, daemon=True).start()
        except OSError:
            AlertRuntime.objects.filter(pk=1).update(worker_status='stopped')
            raise
    return True


def stop_worker():
    runtime, _ = AlertRuntime.objects.get_or_create(pk=1)
    AlertRuntime.objects.filter(pk=runtime.pk).update(stop_requested=True)
