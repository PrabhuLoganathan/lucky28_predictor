"""One ending notification per previously delivered category alert and recipient."""
import hashlib
import json
from collections import defaultdict
from urllib.parse import urlsplit

from django.conf import settings
from django.db.models import TextField
from django.db.models.fields.json import KT
from django.db.models.functions import Cast
from django.urls import reverse
from django.utils import timezone

from games.category_config import CATEGORY_BY_ID, CATEGORIES_BY_NUMBER
from games.models import AlertDelivery, CategoryAlertEvent
from .alerts import queue_delivery
from .group_absence import display_time

ENDING_INVALID = 'Ending evidence changed or cannot be verified.'


def ending_snapshot(event, rule, history, positions):
    from .card_timeline import snapshot_for_round
    """Find the first verified breaker after the original alert's evaluated round."""
    index = positions.get(event.evaluated_round if hasattr(event, 'evaluated_round') else event.snapshot['evaluated_round'])
    if index is None:
        return None
    group = CATEGORY_BY_ID[rule.group_id]

    def active(game):
        member = game.winning_number in group.numbers
        return not member if rule.mode == 'absence' else member

    # A correction that invalidates the original condition is not a new ending.
    if not active(history[index]):
        return None
    end = index + 1
    while end < len(history) and active(history[end]):
        end += 1
    if end == len(history):
        return None
    start = index
    while start > 0 and active(history[start - 1]):
        start -= 1
    game = history[end]
    count = end - start
    lower_bound = start == 0
    count_text = f'{"at least " if lower_bound else ""}{count}'
    detail = (f'Absence ended after {count_text} missed rounds. {game.winning_number} belongs to this group.'
              if rule.mode == 'absence' else
              f'Streak ended after {count_text} consecutive hits. {game.winning_number} is outside this group.')
    path = reverse('game_detail', args=[game.game_no])
    base = getattr(settings, 'ALERT_PUBLIC_BASE_URL', '').rstrip('/')
    url = urlsplit(base)
    evidence = [(item.game_no, item.winning_number) for item in history[start:end + 1]]
    evidence_key = hashlib.sha256(json.dumps(evidence).encode()).hexdigest()
    # Frozen evidence does not need another 150-round snapshot on every poll.
    if evidence_key == event.resolution_snapshot.get('evidence_key'):
        return event.resolution_snapshot
    return dict(event.snapshot, change_type='ended', count=count, lower_bound=lower_bound,
        global_timeline=snapshot_for_round(rule.settings_id, game.game_no),
        ended_number=game.winning_number, ended_at=display_time(game.winner_event_ts),
        result_groups=[g.label for g in CATEGORIES_BY_NUMBER[game.winning_number]],
        period_start=history[start].game_no, game_no=game.game_no, evaluated_round=game.game_no,
        captured_at=display_time(timezone.now()), details_path=path,
        details_url=base + path if url.scheme in ('http', 'https') and url.netloc else '',
        evidence_key=evidence_key,
        matches=[dict(title=f'{group.label} — {rule.mode} ended', group='category', min_plan_rank=1,
                      detail=f'{detail} Ending round: {game.game_no}.')],
        timeline=[dict(number=item.winning_number, size='Small' if item.winning_number < 14 else 'Big')
                  for item in reversed(history[max(0, end - 9):end + 1])])


def reconcile_ending(event, rule, history, positions, current, newly_resolved, invalidated_ids):
    # Existing resolved events without evidence predate this feature; don't replay.
    if not newly_resolved and not event.resolution_snapshot:
        return
    candidate = None if current else ending_snapshot(event, rule, history, positions)
    if candidate:
        if candidate['evidence_key'] != event.resolution_snapshot.get('evidence_key'):
            event.resolution_snapshot = candidate
            event.save(update_fields=['resolution_snapshot'])
    else:
        snapshot = {} if current else {'pending': True}
        if event.resolution_snapshot != snapshot:
            event.resolution_snapshot = snapshot
            event.save(update_fields=['resolution_snapshot'])
        invalidated_ids.append(event.pk)


def queue_endings(config):
    if not config.enabled or not config.notify_changes or config.snapshot.get('blocked'):
        return
    events = {event.pk: event for event in CategoryAlertEvent.objects.filter(
        rule__settings=config, rule__enabled=True, resolved_at__isnull=False,
        resolution_snapshot__change_type='ended').only('id')}
    if not events:
        return
    # Fetch recipients once, instead of scanning the delivery JSON for each old alert.
    originals_by_event = defaultdict(list)
    originals = AlertDelivery.objects.filter(kind='category', status='sent',
        payload__event_id__in=list(events)).select_related('destination').defer('payload').annotate(
        original_event_id=KT('payload__event_id'), original_chat_id=Cast(KT('payload__chat_id'), TextField()))
    for original in originals:
        originals_by_event[original.original_event_id].append(original)
    keys = [f'category-end:{event_id}:{original.destination_id}'
            for event_id, originals in originals_by_event.items() for original in originals]
    existing = {delivery.dedup_key: delivery for delivery in AlertDelivery.objects.filter(
        dedup_key__in=keys).only('id', 'dedup_key', 'status', 'error')}
    now = timezone.now()
    for event_id, originals in originals_by_event.items():
        event = events[event_id]
        # A successful original send may finish after reconciliation; check again
        # each cycle, so that race cannot lose the follow-up.
        for original in originals:
            destination = original.destination
            if (not destination.enabled or destination.routing_type != 'level' or destination.plan_rank < 1
                    or (destination.expires_at and destination.expires_at <= now)
                    or str(original.original_chat_id) != destination.chat_id):
                continue
            key = f'category-end:{event.pk}:{destination.pk}'
            delivery = existing.get(key)
            if delivery is not None and not (delivery.status == 'cancelled' and delivery.error == ENDING_INVALID):
                continue
            payload = dict(event.resolution_snapshot, event_id=event.pk, original_delivery_id=original.pk)
            if delivery is None:
                delivery = queue_delivery(key, destination, 'category_end', payload)
            # A correction can reopen the original period, then a later genuine
            # breaker can close it. Only restore a safely cancelled, unsent ending.
            AlertDelivery.objects.filter(pk=delivery.pk, status='cancelled', error=ENDING_INVALID).update(
                status='pending', error='', available_at=now,
                payload=dict(payload, chat_id=destination.chat_id, use_cards=destination.use_cards))


def delivery_gate(payload):
    from .category_alerts import synchronize
    event = CategoryAlertEvent.objects.select_related('rule').filter(pk=payload.get('event_id')).first()
    if not event:
        return 'cancelled'
    config, _ = synchronize(event.rule.settings_id)
    event.refresh_from_db()
    rule = event.rule
    if not event.resolved_at or event.resolution_snapshot.get('change_type') != 'ended':
        return 'cancelled'
    original = AlertDelivery.objects.filter(pk=payload.get('original_delivery_id'), kind='category',
        payload__event_id=event.pk, status='sent', payload__chat_id=payload.get('chat_id')).first()
    if not original:
        return 'cancelled'
    if (config.snapshot.get('blocked') or not rule.complete or not config.enabled
            or not config.notify_changes or not rule.enabled):
        return 'pending'
    return 'ready'


def refresh_delivery_payload(payload):
    event = CategoryAlertEvent.objects.get(pk=payload['event_id'])
    return dict(payload, **event.resolution_snapshot)
