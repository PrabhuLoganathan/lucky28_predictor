from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from games.models import AlertDestination, AlertRule
from games.services.alert_engine import tip_rules


class Command(BaseCommand):
    help = 'Install tip rules, preserving conditions; optionally route tips exclusively to a dedicated Telegram channel.'

    def add_arguments(self, parser):
        parser.add_argument('--chat-id', help='Telegram channel @username or numeric chat ID. The bot must be an administrator.')
        parser.add_argument('--channel-name', default='Lucky28 Tip Alerts')

    @transaction.atomic
    def handle(self, *args, **options):
        chat_id = options.get('chat_id')
        if chat_id is not None:
            chat_id = chat_id.strip()
            if not chat_id or len(chat_id) > 80:
                raise CommandError('Provide a channel @username or numeric chat ID (maximum 80 characters).')
            destination, new = AlertDestination.objects.get_or_create(chat_id=chat_id, defaults=dict(
                name=options['channel_name'], routing_type='direct', enabled=True,
                send_results=False, send_health=False, use_cards=True))
            if not new:
                raise CommandError('This chat is already configured. Choose a new dedicated channel, or edit its routing in Alerts.')
            destination.full_clean()

        created = 0
        for definition in tip_rules():
            definition = dict(definition)
            _, new = AlertRule.objects.get_or_create(key=definition.pop('key'), defaults=definition)
            created += new
        if chat_id is not None:
            rules = AlertRule.objects.filter(series='tip')
            for rule in rules:
                rule.send_to_levels = False
                rule.save(update_fields=['send_to_levels'])
                rule.destinations.set([destination])
            self.stdout.write(self.style.SUCCESS(
                f'Routed {rules.count()} tip rules exclusively to {destination.name}. '
                'Thresholds and enabled states preserved; result and health messages disabled.'))
        self.stdout.write(self.style.SUCCESS(f'Created {created} tip alert rules. Existing conditions preserved.'))
