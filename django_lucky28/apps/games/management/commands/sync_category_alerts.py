from django.core.management.base import BaseCommand
from games.services.category_alerts import synchronize_all


class Command(BaseCommand):
    help = 'Restore row, column and size/parity alerts without replaying old periods.'

    def handle(self, *args, **options):
        synchronize_all()
        self.stdout.write(self.style.SUCCESS('Category alert state synchronized.'))
