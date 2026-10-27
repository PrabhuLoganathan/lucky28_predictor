from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from games.services.tips import initialize_history


class Command(BaseCommand):
    help = 'Replay saved final settlements into an unused tip monitor, without creating alerts.'

    def add_arguments(self, parser):
        parser.add_argument('--monitor', default=settings.TIP_MONITOR_ID)
        parser.add_argument('--thresholds', nargs='+', type=int, default=[7, 10, 15])

    def handle(self, *args, **options):
        try:
            result = initialize_history(stream_id=options['monitor'], thresholds=options['thresholds'])
        except ValueError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS(f"Tip monitor {options['monitor']}: {result}. Historical alerts suppressed."))
