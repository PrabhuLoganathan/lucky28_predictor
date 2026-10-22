from django.core.management.base import BaseCommand
from games.services.group_absence import synchronize_all


class Command(BaseCommand):
    help = 'Restore group absence counters and evaluate only current eligibility; never replay historical alerts.'

    def handle(self, *args, **options):
        synchronize_all()
        self.stdout.write(self.style.SUCCESS('Group absence counters synchronized.'))
