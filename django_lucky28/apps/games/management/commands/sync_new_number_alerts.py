from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from games.models import AlertDestination, AlertRule
from games.services.alert_engine import new_number_rules


class Command(BaseCommand):
    help = 'Install new-number alerts and optionally route them to a dedicated Telegram channel.'

    def add_arguments(self, parser):
        parser.add_argument('--chat-id', help='A new dedicated channel numeric chat ID or @username.')

    @transaction.atomic
    def handle(self, *args, **options):
        chat_id = options.get('chat_id')
        destination = None
        if chat_id is not None:
            chat_id = chat_id.strip()
            if not chat_id or len(chat_id) > 80:
                raise CommandError('Provide a channel chat ID or @username (maximum 80 characters).')
            if AlertDestination.objects.filter(chat_id=chat_id).exists():
                raise CommandError('This chat is already configured; use a new dedicated channel.')
            destination = AlertDestination(name='Lucky28 New Number Alerts', chat_id=chat_id,
                routing_type='direct', enabled=True, send_results=False, send_health=False, use_cards=True)
            destination.full_clean()
            destination.save()
        for definition in new_number_rules():
            definition = dict(definition)
            rule, _ = AlertRule.objects.get_or_create(key=definition.pop('key'), defaults=definition)
            if destination is not None:
                rule.send_to_levels = False
                rule.save(update_fields=['send_to_levels'])
                rule.destinations.set([destination])
        self.stdout.write(self.style.SUCCESS('New-number rules installed.' +
            (' Routed exclusively to Lucky28 New Number Alerts.' if destination else ' No channel connected.')))
