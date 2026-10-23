"""Persistent absence and streak rules for rows, columns and size/parity groups."""
import hashlib
from collections import defaultdict
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.db.models import TextField
from django.db.models.fields.json import KT
from django.db.models.functions import Cast
from django.urls import reverse
from django.utils import timezone

from games.category_config import CATEGORIES, CATEGORY_BY_ID, CATEGORIES_BY_NUMBER, CATEGORY_MODES
from games.group_config import parse_threshold
from games.models import (GameRound, GroupAbsenceStream, CategoryAlertSettings, CategoryAlertRule,
                          CategoryAlertEvent, CategoryAlertChange, AlertDelivery)
from .group_absence import locked_stream, display_time
from .category_history import observed_suffix
from .alerts import eligible_destinations, queue_delivery
from .category_changes import reconcile_ending, queue_endings, ENDING_INVALID


def ensure_settings(key):
    stream = locked_stream(key)
    config, _ = CategoryAlertSettings.objects.get_or_create(stream=stream)
    existing = {(rule.group_id, rule.mode) for rule in config.rules.all()}
    CategoryAlertRule.objects.bulk_create([
        CategoryAlertRule(settings=config, group_id=group.id, mode=mode)
        for group in CATEGORIES for mode in CATEGORY_MODES if (group.id, mode) not in existing
    ])
    return config


def eligible(config, rule):
    return bool(config.enabled and rule.enabled and rule.complete and rule.threshold
                and rule.count >= rule.threshold)


def rule_status(config, rule):
    if not rule.complete:
        return 'Data incomplete'
    if rule.threshold is None:
        return 'Not configured'
    if not config.enabled or not rule.enabled:
        return 'Disabled'
    return 'Threshold reached' if rule.count >= rule.threshold else 'Below threshold'


def current_snapshot(config, rule, now=None):
    from .card_timeline import snapshot_for_round
    group = CATEGORY_BY_ID[rule.group_id]
    now = now or timezone.now()
    count = f'{"at least " if rule.lower_bound else ""}{rule.count}'
    detail = (f'Absent for {count} completed rounds.' if rule.mode == 'absence'
              else f'Appeared in {count} consecutive completed rounds.')
    path = reverse('game_detail', args=[config.snapshot['end_round']])
    base = getattr(settings, 'ALERT_PUBLIC_BASE_URL', '').rstrip('/')
    url = urlsplit(base)
    return dict(stream=config.stream_id, group_id=group.id, group_name=group.name, family=group.family,
        global_timeline=snapshot_for_round(config.stream_id, config.snapshot['end_round']),
        numbers=list(group.numbers), mode=rule.mode, count=rule.count, threshold=rule.threshold,
        lower_bound=rule.lower_bound, last_number=rule.last_number, last_round=rule.last_round,
        last_timestamp=display_time(rule.last_timestamp), period_start=rule.period_start,
        game_no=config.snapshot['end_round'], evaluated_round=config.snapshot['end_round'],
        captured_at=display_time(now), details_path=path,
        details_url=base + path if url.scheme in ('http', 'https') and url.netloc else '',
        matches=[dict(title=f'{group.label} — {rule.mode}', group='category', min_plan_rank=1,
                      detail=f'{detail} Threshold: {rule.threshold}. Evaluated through {config.snapshot["end_round"]}.')],
        timeline=config.snapshot.get('timeline', []))


@transaction.atomic
def synchronize(key='lucky28', evaluate_current=True):
    config = ensure_settings(key)
    rules = list(config.rules.order_by('group_id', 'mode'))
    history, interrupted, blocked, reason = observed_suffix(key)
    now = timezone.now()
    previous_end = config.snapshot.get('end_round', '')
    config.snapshot = dict(blocked=blocked, interrupted=interrupted, reason=reason,
        observed_rounds=len(history), end_round=history[-1].game_no if history else previous_end,
        last_number=history[-1].winning_number if history else None,
        memberships=[group.id for group in CATEGORIES_BY_NUMBER[history[-1].winning_number]] if history else [],
        timeline=[dict(game_no=game.game_no, number=game.winning_number,
                       size='Small' if game.winning_number < 14 else 'Big') for game in reversed(history[-10:])])
    config.updated_at = now
    config.save(update_fields=['snapshot', 'updated_at'])
    if blocked:
        config.rules.update(complete=False)
        for rule in rules:
            rule.complete = False
        return config, rules
    positions = {game.game_no: index for index, game in enumerate(history)}
    events = defaultdict(list)
    for event in CategoryAlertEvent.objects.filter(rule__settings=config).defer('snapshot').annotate(
            evaluated_round=Cast(KT('snapshot__evaluated_round'), TextField())):
        events[event.rule_id].append(event)
    ended_ids, invalidated_ids = [], []
    for rule in rules:
        group = CATEGORY_BY_ID[rule.group_id]
        hits = [index for index, game in enumerate(history) if game.winning_number in group.numbers]
        last_index = hits[-1] if hits else -1
        last = history[last_index] if hits else None
        rule.last_number = last.winning_number if last else None
        rule.last_round = last.game_no if last else ''
        rule.last_timestamp = last.winner_event_ts if last else None
        if rule.mode == 'absence':
            rule.count = len(history) - last_index - 1
            start = last_index + 1
            anchor = rule.last_round or f'unseen:{history[0].game_no}'
            rule.lower_bound = last is None
            rule.complete = not (interrupted and last is None)
        else:
            start = len(history)
            while start > 0 and history[start - 1].winning_number in group.numbers:
                start -= 1
            rule.count = len(history) - start
            anchor = history[start].game_no if rule.count else 'inactive'
            rule.lower_bound = bool(rule.count and start == 0)
            rule.complete = not (interrupted and start == 0)
        rule.period_start = history[start].game_no if rule.count else ''
        rule.period_key = hashlib.sha256(f'{key}:{rule.group_id}:{rule.mode}:{anchor}'.encode()).hexdigest()
        # Unknown boundaries pause delivery and preserve the old marker until
        # reconciliation or a known hit/break establishes a fresh period.
        if not rule.complete:
            continue
        rule.notified = False
        for event in events[rule.pk]:
            evaluated_index = positions.get(event.evaluated_round, -1)
            current = bool(rule.count and (evaluated_index >= start or event.period_key == rule.period_key))
            if current:
                rule.notified = True
            resolved = None if current else (event.resolved_at or now)
            newly_resolved = event.resolved_at is None and resolved is not None
            if resolved != event.resolved_at:
                event.resolved_at = resolved
                event.save(update_fields=['resolved_at'])
            reconcile_ending(event, rule, history, positions, current, newly_resolved, invalidated_ids)
            if not current:
                ended_ids.append(event.pk)
    if ended_ids:
        AlertDelivery.objects.filter(kind='category', payload__event_id__in=ended_ids,
            status__in=['pending', 'failed']).update(status='cancelled', error='Category absence or streak ended.')
    if invalidated_ids:
        AlertDelivery.objects.filter(kind='category_end', payload__event_id__in=invalidated_ids,
            status__in=['pending', 'failed']).update(status='cancelled', error=ENDING_INVALID)
    CategoryAlertRule.objects.bulk_update(rules, ['count', 'complete', 'lower_bound', 'last_number', 'last_round',
        'last_timestamp', 'period_start', 'period_key', 'notified'])
    if evaluate_current:
        for rule in rules:
            if eligible(config, rule) and not rule.notified:
                CategoryAlertEvent.objects.get_or_create(rule=rule, period_key=rule.period_key,
                    defaults={'snapshot': current_snapshot(config, rule, now)})
                rule.notified = True
                rule.save(update_fields=['notified'])
        by_id = {rule.pk: rule for rule in rules}
        for event in CategoryAlertEvent.objects.filter(rule__settings=config, resolved_at__isnull=True):
            if eligible(config, by_id[event.rule_id]):
                for destination in eligible_destinations(now):
                    queue_delivery(f'category:{event.pk}:{destination.pk}', destination, 'category',
                                   dict(event.snapshot, event_id=event.pk))
        queue_endings(config)
    return config, rules


@transaction.atomic
def save_settings(key, enabled, values, editor, notify_changes=None):
    expected = {(group.id, mode) for group in CATEGORIES for mode in CATEGORY_MODES}
    if set(values) != expected:
        raise ValueError('Supply all 15 groups and both alert types.')
    validated = {pair: dict(enabled=bool(value['enabled']), threshold=parse_threshold(value['threshold'], value['enabled']))
                 for pair, value in values.items()}
    config = ensure_settings(key)
    if notify_changes is not None and config.notify_changes != bool(notify_changes):
        CategoryAlertChange.objects.create(settings=config, group_id='Follow-ups',
            old_value={'enabled': config.notify_changes}, new_value={'enabled': bool(notify_changes)}, editor=editor)
        config.notify_changes = bool(notify_changes)
        config.save(update_fields=['notify_changes'])
    if config.enabled != bool(enabled):
        CategoryAlertChange.objects.create(settings=config, group_id='Global',
            old_value={'enabled': config.enabled}, new_value={'enabled': bool(enabled)}, editor=editor)
        config.enabled = bool(enabled)
        config.save(update_fields=['enabled'])
    for rule in config.rules.all():
        new = validated[(rule.group_id, rule.mode)]
        old = dict(enabled=rule.enabled, threshold=rule.threshold)
        if old != new:
            CategoryAlertChange.objects.create(settings=config, group_id=rule.group_id, mode=rule.mode,
                old_value=old, new_value=new, editor=editor)
            rule.enabled, rule.threshold = new['enabled'], new['threshold']
            rule.save(update_fields=['enabled', 'threshold'])
    return synchronize(key)


def synchronize_all():
    keys = set(GroupAbsenceStream.objects.values_list('key', flat=True))
    keys.update(key or 'lucky28' for key in GameRound.objects.values_list('game_type', flat=True).distinct())
    for key in sorted(keys):
        synchronize(key)


def delivery_gate(payload):
    event = CategoryAlertEvent.objects.select_related('rule').filter(pk=payload.get('event_id')).first()
    if not event or event.resolved_at:
        return 'cancelled'
    config, rules = synchronize(event.rule.settings_id)
    event.refresh_from_db()
    if event.resolved_at:
        return 'cancelled'
    rule = next(rule for rule in rules if rule.pk == event.rule_id)
    return 'ready' if eligible(config, rule) else 'pending'


def refresh_delivery_payload(payload):
    event = CategoryAlertEvent.objects.select_related('rule__settings').get(pk=payload['event_id'])
    return dict(payload, **current_snapshot(event.rule.settings, event.rule))
