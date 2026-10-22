"""At-most-once dispatch with durable claims and conservative ambiguity handling."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from pathlib import Path

import requests
from django.conf import settings
from django.db.models import F
from django.utils import timezone

from games.models import AlertDelivery, AlertRuntime, GameRound
from .alert_presentation import format_message, render_card
from .alert_settings import get_config

_render_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='alert-card')
_render_future = None


def card_with_deadline(payload, kind):
    global _render_future
    # A timed-out render must not create an unbounded work queue.
    if _render_future is not None and not _render_future.done():
        return None
    _render_future = _render_pool.submit(render_card, payload, kind)
    try:
        return _render_future.result(timeout=2.0)
    except Exception:
        return None


def recover_abandoned_claims():
    # The caller holds the exclusive worker lease. Never resend a crashed claim.
    return AlertDelivery.objects.filter(status='sending').update(
        status='uncertain', error='Worker stopped after claiming; delivery may have occurred.')


def deliver_one(delivery_id):
    config = get_config()
    if not config.telegram_enabled or not config.bot_token:
        return False
    now = timezone.now()
    # Conditional UPDATE is atomic on both SQLite and databases with row locks.
    claimed = AlertDelivery.objects.filter(pk=delivery_id, status='pending', available_at__lte=now).update(
        status='sending', claimed_at=now, attempts=F('attempts') + 1)
    if not claimed:
        return False
    delivery = AlertDelivery.objects.select_related('destination', 'evaluation__game').get(pk=delivery_id)
    destination = delivery.destination

    def finish(status, **fields):
        AlertDelivery.objects.filter(pk=delivery.pk, status='sending').update(status=status, **fields)

    if not destination.enabled or (destination.expires_at and destination.expires_at <= now) or destination.chat_id != delivery.payload['chat_id']:
        finish('cancelled', error='Destination disabled, changed or expired.')
        return True
    matches = delivery.payload.get('matches', [])
    if any(m['min_plan_rank'] > destination.plan_rank for m in matches):
        finish('cancelled', error='Subscription rank no longer permits this payload.')
        return True
    if delivery.kind == 'window':
        from .window_alerts import delivery_gate as window_delivery_gate
        gate = window_delivery_gate(delivery.payload)
        if gate != 'ready':
            finish(gate, available_at=now + timedelta(seconds=30), error='10-game alert paused, expired or superseded.')
            return True
    if delivery.kind in ('category', 'category_end'):
        if delivery.kind == 'category_end':
            from .category_changes import delivery_gate as category_delivery_gate, refresh_delivery_payload as category_payload
        else:
            from .category_alerts import delivery_gate as category_delivery_gate, refresh_delivery_payload as category_payload
        gate = category_delivery_gate(delivery.payload)
        if gate != 'ready':
            error = ('Ending evidence changed or cannot be verified.' if delivery.kind == 'category_end' and gate == 'cancelled'
                     else 'Category alert paused, resolved or data incomplete.')
            finish(gate, available_at=now + timedelta(seconds=30), error=error)
            return True
        delivery.payload = category_payload(delivery.payload)
        AlertDelivery.objects.filter(pk=delivery.pk, status='sending').update(payload=delivery.payload)
    if delivery.kind == 'group':
        from .group_absence import delivery_gate, refresh_delivery_payload
        gate = delivery_gate(delivery.payload)
        if gate != 'ready':
            finish(gate, available_at=now + timedelta(seconds=30),
                   error='Group absence resolved.' if gate == 'cancelled' else 'Group alerts paused or data incomplete.')
            return True
        delivery.payload = refresh_delivery_payload(delivery.payload)
        AlertDelivery.objects.filter(pk=delivery.pk, status='sending').update(payload=delivery.payload)
    if delivery.kind == 'alert':
        game = delivery.evaluation.game if delivery.evaluation else None
        if not game or game.has_winner or (now - delivery.created_at).total_seconds() > config.max_event_age_seconds:
            finish('cancelled', error='Round completed or alert expired before dispatch.')
            return True
    if delivery.kind == 'result':
        if not destination.send_results:
            finish('cancelled', error='Result follow-ups disabled.')
            return True
        original = AlertDelivery.objects.filter(evaluation=delivery.evaluation, destination=destination, kind='alert').first()
        if not original or original.status in ('failed', 'uncertain', 'cancelled'):
            finish('cancelled', error='Original alert was not confirmed sent.')
            return True
        if original.status != 'sent':
            finish('pending', available_at=now + timedelta(seconds=2))
            return True
    if delivery.kind == 'health' and not destination.send_health:
        finish('cancelled', error='Health warnings disabled.')
        return True
    if delivery.kind == 'health' and not AlertRuntime.objects.filter(
            pk=1, outage_active=True, outage_number=delivery.payload.get('outage_number')).exists():
        finish('cancelled', error='Collection resumed or this outage was superseded.')
        return True
    card = card_with_deadline(delivery.payload, delivery.kind) if delivery.payload.get('use_cards') and delivery.kind != 'test' else None
    text = format_message(delivery.payload, delivery.kind, limit=1024 if card else 4096)
    method = 'sendPhoto' if card else 'sendMessage'
    data = {'chat_id': delivery.payload['chat_id'], 'parse_mode': 'HTML', 'caption' if card else 'text': text}
    if delivery.kind == 'alert' and not GameRound.objects.filter(pk=delivery.evaluation.game_id, has_winner=False).exists():
        finish('cancelled', error='Round completed during payload preparation.')
        return True
    # Archive before HTTP. If disk persistence fails, nothing was sent.
    try:
        directory = Path(settings.ALERT_STATE_DIR) / 'artifacts'
        directory.mkdir(parents=True, exist_ok=True)
        artifact = directory / f'{delivery.pk}.json'
        artifact.write_text(json.dumps({'method': method, 'data': data}, ensure_ascii=False), encoding='utf-8')
        if card:
            (directory / f'{delivery.pk}.jpg').write_bytes(card)
        AlertDelivery.objects.filter(pk=delivery.pk).update(artifact_path=str(artifact))
    except OSError:
        finish('pending' if delivery.kind in ('group', 'window', 'category', 'category_end') else 'failed',
               available_at=now + timedelta(seconds=30), error='Unable to archive outgoing artifact; nothing sent.')
        return True
    if delivery.kind == 'group':
        gate = delivery_gate(delivery.payload)
        if gate != 'ready':
            finish(gate, available_at=now + timedelta(seconds=30), error='Group eligibility changed before dispatch.')
            return True
    if delivery.kind == 'window':
        gate = window_delivery_gate(delivery.payload)
        if gate != 'ready':
            finish(gate, available_at=now + timedelta(seconds=30), error='10-game eligibility changed before dispatch.')
            return True
    if delivery.kind in ('category', 'category_end'):
        gate = category_delivery_gate(delivery.payload)
        if (gate == 'ready' and delivery.kind == 'category_end'
                and category_payload(delivery.payload).get('evidence_key') != delivery.payload.get('evidence_key')):
            gate = 'pending'
        if gate != 'ready':
            error = ('Ending evidence changed or cannot be verified.' if delivery.kind == 'category_end' and gate == 'cancelled'
                     else 'Category eligibility changed before dispatch.')
            finish(gate, available_at=now + timedelta(seconds=30), error=error)
            return True
    try:
        response = requests.post(
            f'https://api.telegram.org/bot{config.bot_token}/{method}',
            data=data, files={'photo': ('alert.jpg', card, 'image/jpeg')} if card else None,
            timeout=(5, 10), allow_redirects=False,
        )
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        result = body.get('result')
        message_id = result.get('message_id') if isinstance(result, dict) else None
        if 200 <= response.status_code < 300 and body.get('ok') is True and type(message_id) is int:
            finish('sent', sent_at=timezone.now(), message_id=message_id, error='')
        elif response.status_code == 429 and body.get('ok') is False:
            try:
                retry_after = min(86400, max(1, int(body.get('parameters', {}).get('retry_after', 30))))
            except (ValueError, TypeError, AttributeError):
                retry_after = 30
            finish('pending', available_at=now + timedelta(seconds=retry_after), error='Telegram rate limit; retry scheduled.')
        elif 400 <= response.status_code < 500:
            finish('failed', error=f'Telegram rejected request (HTTP {response.status_code}).')
        else:
            finish('uncertain', error=f'Unconfirmed Telegram response (HTTP {response.status_code}); not retried.')
    except requests.RequestException:
        # Do not log the exception: requests exceptions can contain the bot token.
        finish('uncertain', error='Network error after claim; delivery may have occurred. Not retried.')
    return True


def deliver_pending(limit=20):
    ids = list(AlertDelivery.objects.filter(status='pending', available_at__lte=timezone.now())
               .order_by('pk').values_list('pk', flat=True)[:limit])
    count = 0
    for pk in ids:
        if AlertRuntime.objects.filter(pk=1, stop_requested=True).exists():
            break
        count += deliver_one(pk)
    return count
