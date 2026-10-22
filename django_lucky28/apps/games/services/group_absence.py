"""Rebuild ordered observed history, then evaluate only the current absence.

All mutations and outbox writes share the stream write lock. Reconciliation never
walks historical thresholds, and notification evidence survives corrections.
"""
import hashlib
import re
from collections import defaultdict
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone

from games.group_config import COLOR_GROUPS, GROUP_BY_ID, GROUP_BY_NUMBER, parse_threshold
from games.models import (GameRound, GroupAbsenceStream, GroupAbsenceState,
                          GroupAbsenceChange, GroupAbsenceEvent, GroupDataIssue, AlertDelivery)
from .alerts import eligible_destinations, queue_delivery


def stream_key(game):
    return game.game_type or 'lucky28'


def stream_games(key):
    query = GameRound.objects.all()
    return query.filter(Q(game_type='lucky28') | Q(game_type='') | Q(game_type__isnull=True)) if key == 'lucky28' else query.filter(game_type=key)


def locked_stream(key):
    GroupAbsenceStream.objects.get_or_create(key=key)
    GroupAbsenceStream.objects.filter(pk=key).update(version=F('version') + 1)
    stream = GroupAbsenceStream.objects.select_for_update().get(pk=key)
    for group in COLOR_GROUPS:
        GroupAbsenceState.objects.get_or_create(stream=stream, group_id=group.id)
    return stream


def sequence_id(round_id):
    match = re.fullmatch(r'(.*?)([0-9]+)', round_id)
    return (match[1], int(match[2])) if match else None


def valid_result(game):
    return (game.has_winner and type(game.winning_number) is int and 0 <= game.winning_number <= 27
            and game.status in (None, 3, 4) and game.winner_event_ts is not None)


@transaction.atomic
def report_issue(key, round_id, reason):
    stream = locked_stream(key)
    # A rejected duplicate cannot invalidate an already accepted winner.
    saved = stream_games(key).filter(game_no=round_id).first()
    if saved and valid_result(saved):
        return
    GroupDataIssue.objects.update_or_create(stream=stream, round_id=round_id,
                                           defaults={'reason': reason[:240]})
    stream.dirty = True
    stream.complete = False
    stream.incomplete_reason = f'Round {round_id}: {reason}'
    stream.save()


def rebuild(stream, states):
    games = list(stream_games(stream.key).only('game_no', 'has_winner', 'winning_number', 'status',
                                             'winner_event_ts', 'pre_event_ts', 'created_at'))
    sequences = [sequence_id(game.game_no) for game in games]
    sequenced = bool(games) and all(sequences) and len({seq[0] for seq in sequences}) == 1
    if sequenced:
        games.sort(key=lambda game: (sequence_id(game.game_no)[1], game.pk))
    else:
        games.sort(key=lambda game: (game.winner_event_ts or game.pre_event_ts or game.created_at, game.pk))
    # An open next round is expected; an unfinished round before a later result is a gap.
    completed_positions = [i for i, game in enumerate(games) if game.has_winner]
    boundary = max(completed_positions, default=-1)
    relevant = games[:boundary + 1]
    reasons = []
    if relevant and stream.consecutive_ids and not sequenced:
        reasons.append('Round IDs must share a prefix and end in consecutive integers; continuity cannot be verified.')
    valid = []
    previous = None
    for game in relevant:
        seq = sequence_id(game.game_no) if sequenced else None
        if stream.consecutive_ids and previous is not None and seq[1] != previous + 1:
            reasons.append(f'Missing round IDs between {previous} and {seq[1]}.')
        if seq:
            previous = seq[1]
        if valid_result(game):
            valid.append(game)
        else:
            reasons.append(f'Round {game.game_no} is missing, pending, cancelled or invalid.')
    valid_ids = {game.game_no for game in valid}
    GroupDataIssue.objects.filter(stream=stream, round_id__in=valid_ids).delete()
    reasons.extend(f'Round {issue.round_id}: {issue.reason}' for issue in GroupDataIssue.objects.filter(stream=stream))
    stream.complete = bool(valid) and not reasons
    stream.incomplete_reason = ' '.join(reasons[:10]) if reasons else ('' if valid else 'No completed results available.')
    stream.observed_rounds = len(valid)
    stream.last_round = valid[-1].game_no if valid else ''
    stream.last_timestamp = valid[-1].winner_event_ts if valid else None
    positions = {game.game_no: index for index, game in enumerate(valid)}
    last = {}
    for index, game in enumerate(valid):
        last[GROUP_BY_NUMBER[game.winning_number].id] = (index, game)
    events = defaultdict(list)
    for event in GroupAbsenceEvent.objects.filter(stream=stream):
        events[event.group_id].append(event)
    now = timezone.now()
    for state in states:
        index, game = last.get(state.group_id, (-1, None))
        state.absence = len(valid) - index - 1
        state.last_number = game.winning_number if game else None
        state.last_round = game.game_no if game else ''
        state.last_timestamp = game.winner_event_ts if game else None
        state.period_key = hashlib.sha256(f'{stream.key}:{state.group_id}:{state.last_round or "unseen"}'.encode()).hexdigest()
        state.notified = False
        for event in events[state.group_id]:
            # Keep the notification marker if a correction merges/splits a period
            # but the notification was evaluated after its new last appearance.
            evaluated = positions.get(event.snapshot['evaluated_round'], -1)
            current = evaluated > index or (event.period_key == state.period_key and state.absence > 0)
            if current:
                state.notified = True
            resolved = None if current else (event.resolved_at or now)
            if event.resolved_at != resolved:
                event.resolved_at = resolved
                event.save(update_fields=['resolved_at'])
            if not current:
                AlertDelivery.objects.filter(kind='group', payload__event_id=event.pk,
                                             status__in=['pending', 'failed']).update(
                    status='cancelled', error='Absence resolved or superseded during reconciliation.')
        state.save()
    stream.dirty = False
    stream.save()


def eligible(stream, state):
    return (stream.complete and stream.enabled and state.enabled and state.threshold is not None
            and state.absence >= state.threshold)


def display_time(value):
    return timezone.localtime(value).isoformat() if value else None


def current_snapshot(stream, state, now):
    from .card_timeline import snapshot_for_round
    group = GROUP_BY_ID[state.group_id]
    snapshot = dict(stream=stream.key, group_id=group.id, color=group.name, numbers=list(group.numbers),
                    global_timeline=snapshot_for_round(stream.key, stream.last_round),
                    absence=state.absence, threshold=state.threshold, lower_bound=not bool(state.last_round),
                    last_number=state.last_number, last_round=state.last_round,
                    last_timestamp=display_time(state.last_timestamp), evaluated_round=stream.last_round,
                    captured_at=display_time(now), game_no=stream.last_round, matches=[],
                    details_path=reverse('game_detail', args=[stream.last_round]))
    base = getattr(settings, 'ALERT_PUBLIC_BASE_URL', '').rstrip('/')
    public_url = urlsplit(base)
    snapshot['details_url'] = base + snapshot['details_path'] if public_url.scheme in ('http', 'https') and public_url.netloc else ''
    return snapshot


def evaluate(stream, states):
    now = timezone.now()
    for state in states:
        if not eligible(stream, state) or state.notified:
            continue
        snapshot = current_snapshot(stream, state, now)
        GroupAbsenceEvent.objects.get_or_create(stream=stream, group_id=state.group_id,
                                                period_key=state.period_key, defaults={'snapshot': snapshot})
        state.notified = True
        state.save(update_fields=['notified'])
    # An event is durable even when no destinations exist yet. Destination fanout
    # uses the same event and dedup keys across worker restarts and settings saves.
    state_map = {state.group_id: state for state in states}
    for event in GroupAbsenceEvent.objects.filter(stream=stream, resolved_at__isnull=True):
        if not eligible(stream, state_map[event.group_id]):
            continue
        for destination in eligible_destinations(now):
            queue_delivery(f'group:{event.pk}:{destination.pk}', destination, 'group',
                           dict(event.snapshot, event_id=event.pk))


@transaction.atomic
def synchronize(key='lucky28', evaluate_current=True, force=False):
    stream = locked_stream(key)
    states = list(stream.groups.order_by('group_id'))
    if stream.dirty or force:
        rebuild(stream, states)
    if evaluate_current:
        evaluate(stream, states)
    return stream, states


def synchronize_all():
    keys = set(GroupAbsenceStream.objects.values_list('key', flat=True))
    keys.update(key or 'lucky28' for key in GameRound.objects.values_list('game_type', flat=True).distinct())
    for key in sorted(keys):
        synchronize(key)


@transaction.atomic
def save_settings(key, enabled, values, editor):
    # Validate the entire submitted configuration before writing anything.
    if set(values) != set(GROUP_BY_ID):
        raise ValueError('Settings must contain all seven groups.')
    validated = {group: dict(enabled=bool(value['enabled']),
                            threshold=parse_threshold(value['threshold'], value['enabled']))
                 for group, value in values.items()}
    stream = locked_stream(key)
    if stream.enabled != bool(enabled):
        GroupAbsenceChange.objects.create(stream=stream, group_id='Global',
            old_value={'enabled': stream.enabled}, new_value={'enabled': bool(enabled)}, editor=editor)
        stream.enabled = bool(enabled)
        stream.save(update_fields=['enabled'])
    for state in stream.groups.all():
        old = dict(enabled=state.enabled, threshold=state.threshold)
        new = validated[state.group_id]
        if old != new:
            GroupAbsenceChange.objects.create(stream=stream, group_id=state.group_id,
                                              old_value=old, new_value=new, editor=editor)
            state.enabled, state.threshold = new['enabled'], new['threshold']
            state.save(update_fields=['enabled', 'threshold'])
    return synchronize(key)


def alert_state(stream, state):
    if not stream.complete:
        return 'Data incomplete'
    if state.threshold is None:
        return 'Not configured'
    if not stream.enabled or not state.enabled:
        return 'Disabled'
    return 'Threshold reached' if state.absence >= state.threshold else 'Below threshold'


def delivery_gate(payload):
    """Recheck at dispatch: pause pending events, cancel resolved events."""
    event = GroupAbsenceEvent.objects.filter(pk=payload.get('event_id')).first()
    if not event or event.resolved_at:
        return 'cancelled'
    stream, states = synchronize(event.stream_id)
    event.refresh_from_db()
    if event.resolved_at:
        return 'cancelled'
    state = next(state for state in states if state.group_id == event.group_id)
    return 'ready' if eligible(stream, state) else 'pending'


def refresh_delivery_payload(payload):
    """Use current evidence for an unsent event after corrections/settings edits.

    The event's original evidence remains in history; the same delivery key is
    retained. This prevents an old queued snapshot describing a corrected hit.
    """
    stream = GroupAbsenceStream.objects.get(pk=payload['stream'])
    state = stream.groups.get(group_id=payload['group_id'])
    return dict(payload, **current_snapshot(stream, state, timezone.now()))
