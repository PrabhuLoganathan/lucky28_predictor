"""Explicitly enabled tip sender, using the app's saved Telegram configuration."""
import requests
from django.db import transaction
from django.utils import timezone

from games.models import AlertDestination
from .alert_settings import get_config
from .tips import TipMonitor


def bind_destination(monitor, destination_id):
    with transaction.atomic():
        stream = monitor._lock()
        destination = AlertDestination.objects.get(pk=destination_id)
        if not destination.enabled or (destination.expires_at and destination.expires_at <= timezone.now()):
            raise ValueError('Choose an enabled, unexpired alert destination.')
        if stream.delivery_destination_id is not None and (
                stream.delivery_destination_id != destination_id or stream.delivery_chat_id != destination.chat_id):
            raise ValueError('This monitor is bound to a different destination. Use a new monitor for replay.')
        stream.delivery_destination = destination
        stream.delivery_chat_id = destination.chat_id
        stream.save(update_fields=['delivery_destination', 'delivery_chat_id'])


def dispatch_telegram(stream_id, *, limit=20):
    monitor = TipMonitor(stream_id=stream_id)
    config = get_config()
    if not config.telegram_enabled or not config.bot_token:
        return 0

    def send(event):
        # Recheck settings and recipient on each retry. Never follow a changed
        # chat ID or silently deliver the queue to a new recipient.
        config = get_config()
        stream = monitor._lock()
        destination = stream.delivery_destination
        if (not config.telegram_enabled or not config.bot_token or destination is None
                or not destination.enabled or destination.chat_id != stream.delivery_chat_id
                or (destination.expires_at and destination.expires_at <= timezone.now())):
            return False
        response = requests.post(f'https://api.telegram.org/bot{config.bot_token}/sendMessage',
                                 data={'chat_id': stream.delivery_chat_id, 'text': event['message']},
                                 timeout=(5, 10), allow_redirects=False)
        response.raise_for_status()
        body = response.json()
        if (not isinstance(body, dict) or body.get('ok') is not True
                or not isinstance(body.get('result'), dict)
                or type(body['result'].get('message_id')) is not int):
            raise ValueError('Telegram did not acknowledge the message.')

    return monitor.dispatch(send, limit=limit)
