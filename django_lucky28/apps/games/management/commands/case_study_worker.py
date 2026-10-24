"""Run the independent, read-only-to-games case study recorder."""
import fcntl
import signal
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from games.services.case_study import initialize, journal_path, synchronize, worker_error


class Command(BaseCommand):
    help = 'Record independent Number Game case studies; never changes results or sends alerts.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Backfill/reconcile once and exit.')
        parser.add_argument('--interval', type=float, default=1.0, help='Polling interval in seconds (minimum 0.5).')

    def handle(self, *args, **options):
        path = journal_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix('.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.stdout.write('Case study recorder is already running.')
                return
            initialize()
            stopped = False

            def stop(signum, frame):
                nonlocal stopped
                stopped = True

            old_term = signal.signal(signal.SIGTERM, stop)
            try:
                self.stdout.write(f'Case study journal: {path}', ending='\n')
                while not stopped:
                    try:
                        counts = synchronize()
                        if counts['forecasts'] or counts['reviews']:
                            self.stdout.write(f"Recorded {counts['forecasts']} forecasts, {counts['reviews']} result reviews.")
                    except Exception as error:
                        worker_error(str(error))
                        if options['once']:
                            raise
                        self.stderr.write(f'Case study recorder will retry: {error}')
                    finally:
                        close_old_connections()
                    if options['once']:
                        break
                    time.sleep(max(0.5, options['interval']))
            except KeyboardInterrupt:
                pass
            finally:
                signal.signal(signal.SIGTERM, old_term)
