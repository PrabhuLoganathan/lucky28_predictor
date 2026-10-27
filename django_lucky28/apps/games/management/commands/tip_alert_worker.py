"""Delivery is opt-in; normal ingestion only creates local events."""
import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from games.models import AlertDestination
from games.services.tips import TipMonitor
from games.services.tip_delivery import bind_destination, dispatch_telegram


class Command(BaseCommand):
    help = 'Send queued tip events to an existing alert destination and retry even without new rounds.'

    def add_arguments(self, parser):
        parser.add_argument('--monitor', default=settings.TIP_MONITOR_ID)
        parser.add_argument('--destination', type=int, required=True)
        parser.add_argument('--once', action='store_true')
        parser.add_argument('--interval', type=float, default=30)

    def handle(self, *args, **options):
        if not 1 <= options['interval'] <= 3600:
            raise CommandError('Interval must be between 1 and 3600 seconds.')
        try:
            bind_destination(TipMonitor(stream_id=options['monitor']), options['destination'])
        except (ValueError, AlertDestination.DoesNotExist) as error:
            raise CommandError(str(error)) from error
        stopped = False

        def stop(*args):
            nonlocal stopped
            stopped = True

        old_handler = signal.signal(signal.SIGTERM, stop)
        try:
            self.stdout.write('Tip delivery worker started. Telegram must also be enabled in alert settings.')
            while not stopped:
                try:
                    sent = dispatch_telegram(options['monitor'])
                    if sent:
                        self.stdout.write(f'Sent {sent} tip events.')
                except Exception:
                    if options['once']:
                        raise
                    self.stderr.write('Tip delivery pass failed; queued events will retry.')
                finally:
                    close_old_connections()
                if options['once']:
                    break
                # Short sleeps allow cooperative shutdown even at long intervals.
                deadline = time.monotonic() + options['interval']
                while not stopped and time.monotonic() < deadline:
                    time.sleep(min(0.5, max(0, deadline - time.monotonic())))
        except KeyboardInterrupt:
            pass
        finally:
            signal.signal(signal.SIGTERM, old_handler)
