from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from games.models import AlertDestination, WindowAlertState
from games.services.group_absence import locked_stream
from games.services.window_alerts import synchronize


class Command(BaseCommand):
    help = 'Enable 10-game drought alerts and add an existing destination without changing other routes.'

    def add_arguments(self, parser):
        parser.add_argument('--chat-id', required=True)
        parser.add_argument('--stream', default='lucky28')

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            destination = AlertDestination.objects.get(chat_id=options['chat_id'].strip())
        except AlertDestination.DoesNotExist:
            raise CommandError('The destination is not configured.')
        if not destination.enabled or destination.routing_type != 'direct':
            raise CommandError('Choose an enabled direct-only destination.')
        stream = locked_stream(options['stream'])
        state, _ = WindowAlertState.objects.get_or_create(stream=stream)
        state.drought_enabled = True
        state.save(update_fields=['drought_enabled'])
        state.drought_destinations.add(destination)
        synchronize(options['stream'])
        self.stdout.write(self.style.SUCCESS(f'Drought alerts enabled and routed to {destination.name}.'))
