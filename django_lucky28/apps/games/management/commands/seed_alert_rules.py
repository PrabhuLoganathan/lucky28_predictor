from django.core.management.base import BaseCommand
from games.models import AlertRule
from games.services.alert_engine import default_rules


class Command(BaseCommand):
    help = 'Install Lucky28 alert defaults without replacing customized rules.'

    def handle(self, *args, **options):
        created = 0
        for defaults in default_rules():
            defaults = dict(defaults)
            _, new = AlertRule.objects.get_or_create(key=defaults.pop('key'), defaults=defaults)
            created += new
        self.stdout.write(self.style.SUCCESS(f'Created {created} alert rules.'))
