from django.core.management.base import BaseCommand
from games.models import AlertRule
from games.services.alert_engine import tip_rules


class Command(BaseCommand):
    help = 'Install the two tip rules in the regular alert system, preserving saved customizations.'

    def handle(self, *args, **options):
        created = 0
        for definition in tip_rules():
            definition = dict(definition)
            _, new = AlertRule.objects.get_or_create(key=definition.pop('key'), defaults=definition)
            created += new
        self.stdout.write(self.style.SUCCESS(f'Created {created} tip alert rules. Existing rules preserved.'))
