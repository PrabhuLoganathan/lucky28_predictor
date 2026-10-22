from django.core.management.base import BaseCommand
from games.services.window_alerts import synchronize_all


class Command(BaseCommand):
    help = 'Restore latest-ten alert state without replaying historical windows.'

    def handle(self, *args, **options):
        synchronize_all()
        self.stdout.write(self.style.SUCCESS('10-game alert state synchronized.'))
