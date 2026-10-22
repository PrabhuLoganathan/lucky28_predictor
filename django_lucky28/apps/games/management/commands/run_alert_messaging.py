from pathlib import Path
import signal
import threading

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone

from games.models import AlertRuntime
from games.services.alerts import check_collection_health
from games.services.alert_delivery import deliver_pending, recover_abandoned_claims
from games.services.alert_settings import get_config


class Command(BaseCommand):
    help = 'Run the leased Telegram delivery worker (outbound delivery must be enabled).'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Process one batch and exit.')
        parser.add_argument('--managed', action='store_true', help='Respect a stop request received during UI startup.')

    def handle(self, *args, **options):
        try:
            import fcntl
        except ImportError as error:
            raise CommandError('The delivery worker requires a POSIX file lock (macOS/Linux).') from error
        config = get_config()
        if config.telegram_enabled and not config.bot_token:
            raise CommandError('Add a bot token in Alerts → Telegram & worker before enabling delivery.')
        directory = Path(settings.ALERT_STATE_DIR)
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / 'worker.lock').open('a') as lease:
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise CommandError('An alert messaging worker already holds the lease.') from error
            stopped = threading.Event()
            previous = {}
            if threading.current_thread() is threading.main_thread():
                for signum in (signal.SIGINT, signal.SIGTERM):
                    previous[signum] = signal.signal(signum, lambda *_: stopped.set())
            try:
                recover_abandoned_claims()
                # Re-arm outage timing on a worker start, with a full grace period.
                AlertRuntime.objects.get_or_create(pk=1)
                if not options['managed']:
                    AlertRuntime.objects.filter(pk=1).update(stop_requested=False)
                AlertRuntime.objects.filter(pk=1).update(monitoring_started_at=timezone.now())
                failures = 0
                while not stopped.is_set():
                    try:
                        close_old_connections()
                        if AlertRuntime.objects.filter(pk=1, stop_requested=True).exists():
                            break
                        from games.services.group_absence import synchronize_all
                        synchronize_all()
                        from games.services.window_alerts import synchronize_all as synchronize_windows
                        synchronize_windows()
                        from games.services.category_alerts import synchronize_all as synchronize_categories
                        synchronize_categories()
                        check_collection_health()
                        deliver_pending(limit=3)
                        failures = 0
                    except Exception as error:
                        failures += 1
                        # Avoid secret-bearing HTTP exception text.
                        self.stderr.write(f'Alert worker cycle failed ({type(error).__name__}).')
                        if options['once']:
                            raise CommandError('Alert worker cycle failed; inspect the queue.') from None
                    if options['once']:
                        break
                    stopped.wait(min(30, 2 ** min(failures + 1, 5)) if failures else 2)
            finally:
                AlertRuntime.objects.filter(pk=1).update(worker_status='stopped')
                for signum, handler in previous.items():
                    signal.signal(signum, handler)
