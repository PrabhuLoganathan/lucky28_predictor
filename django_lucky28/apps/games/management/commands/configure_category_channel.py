"""Route a category family to a dedicated channel without changing conditions."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from games.category_config import COMBO_GROUPS, EXTREME_GROUPS, BORDER_GROUPS, ROW_GROUPS
from games.models import AlertDestination, CategoryAlertRule
from games.services.category_alerts import ensure_settings

FAMILIES = {
    'rows': ('Lucky28 Row Alerts', ROW_GROUPS),
    'combinations': ('Lucky28 Combination Alerts', COMBO_GROUPS),
    'extremes': ('Lucky28 Extreme Number Alerts', EXTREME_GROUPS),
    'borders': ('Lucky28 Board Border Alerts', BORDER_GROUPS),
}


class Command(BaseCommand):
    help = 'Route one category family exclusively to a new Telegram channel, preserving thresholds and enabled states.'

    def add_arguments(self, parser):
        parser.add_argument('family', choices=FAMILIES)
        parser.add_argument('--chat-id', required=True)
        parser.add_argument('--stream', default='lucky28')

    @transaction.atomic
    def handle(self, *args, **options):
        name, groups = FAMILIES[options['family']]
        chat_id = options['chat_id'].strip()
        if not chat_id or len(chat_id) > 80:
            raise CommandError('Provide a Telegram channel @username or numeric chat ID, at most 80 characters.')
        if AlertDestination.objects.filter(chat_id=chat_id).exists():
            raise CommandError('This channel is already configured. Choose a new dedicated channel.')
        config = ensure_settings(options['stream'])
        destination = AlertDestination(name=name, chat_id=chat_id, routing_type='direct',
            enabled=True, use_cards=True, send_results=False, send_health=False)
        destination.full_clean()
        destination.save()
        rules = list(CategoryAlertRule.objects.select_for_update().filter(
            settings=config, group_id__in=[group.id for group in groups]))
        for rule in rules:
            rule.send_to_levels = False
            rule.save(update_fields=['send_to_levels'])
            rule.destinations.set([destination])
        active = sum(rule.enabled and rule.threshold is not None for rule in rules)
        self.stdout.write(self.style.SUCCESS(
            f'{name}: routed {len(rules)} rules ({active} enabled) exclusively to {chat_id}. '
            f'Category alerts globally enabled: {config.enabled}. Conditions preserved.'))
