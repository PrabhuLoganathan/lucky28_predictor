"""Independent, thresholded color absence endings with immutable evidence."""
from urllib.parse import urlsplit

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from games.group_config import GROUP_BY_NUMBER
from games.models import GroupAbsenceEnding, AlertDelivery, GroupAbsenceState
from .alerts import eligible_destinations, queue_delivery
from .group_absence import sequence_id, valid_result, stream_games, display_time
from .alert_settings import get_config


def evidence_valid(event, games=None):
    evidence = event.snapshot['evidence']
    if games is None:
        games = {g.game_no: g for g in stream_games(event.stream_id).filter(
            game_no__in=[r[0] for r in evidence])}
    return all(round_id in games and valid_result(games[round_id])
               and games[round_id].winning_number == number for round_id, number in evidence)


def reconcile(stream, states, history, previous_round, saved_games):
    """Only new results after the saved cursor can create an ending.

    History is a verified contiguous suffix. An exact ending needs a prior
    matching result inside that suffix, not a lower-bound gap across an outage.
    """
    previous = sequence_id(previous_round) if previous_round else None
    by_id = {state.group_id: state for state in states}
    last = {}
    for index, game in enumerate(history):
        group = GROUP_BY_NUMBER[game.winning_number]
        start = last.get(group.id)
        last[group.id] = index
        current = sequence_id(game.game_no)
        if (not previous or not current or previous[0] != current[0]
                or current[1] <= previous[1] or start is None):
            continue
        state = by_id[group.id]
        count = index - start - 1
        if (not stream.enabled or not state.ending_enabled or state.ending_threshold is None
                or count < state.ending_threshold):
            continue
        if not -5 <= (timezone.now() - game.winner_event_ts).total_seconds() <= get_config().max_event_age_seconds:
            continue
        if GroupAbsenceEnding.objects.filter(stream=stream, group_id=group.id,
                                              ending_round=game.game_no).exists():
            continue
        from .card_timeline import snapshot_for_round
        path = reverse('game_detail', args=[game.game_no])
        base = getattr(settings, 'ALERT_PUBLIC_BASE_URL', '').rstrip('/')
        url = urlsplit(base)
        snapshot = dict(stream=stream.key, group_id=group.id, group_name=f'{group.id} · {group.name}',
            color=group.name, numbers=list(group.numbers), mode='absence', change_type='ended',
            count=count, absence=count, lower_bound=False, threshold=state.ending_threshold,
            last_round=history[start].game_no, last_number=history[start].winning_number,
            ended_number=game.winning_number, ended_at=display_time(game.winner_event_ts),
            evaluated_round=game.game_no, game_no=game.game_no, captured_at=display_time(timezone.now()),
            details_path=path, details_url=base + path if url.scheme in ('http', 'https') and url.netloc else '',
            global_timeline=snapshot_for_round(stream.key, game.game_no),
            evidence=[[r.game_no, r.winning_number] for r in history[start:index+1]],
            matches=[dict(title=f'{group.name} absence ended', group='color', min_plan_rank=1,
                          detail=f'{game.winning_number} ended {count} missed rounds. Threshold: {state.ending_threshold}.')])
        event = GroupAbsenceEnding.objects.create(stream=stream, group_id=group.id,
                                                  ending_round=game.game_no, snapshot=snapshot)
        # Fan out only when the ending is created, never replay old endings to
        # newly added destinations or after changing thresholds.
        for destination in eligible_destinations(timezone.now()):
            queue_delivery(f'group-end:{event.pk}:{destination.pk}', destination, 'group_end',
                           dict(snapshot, event_id=event.pk))
    saved_by_id = {game.game_no: game for game in saved_games}
    for event in GroupAbsenceEnding.objects.filter(stream=stream, invalidated=False):
        if not evidence_valid(event, saved_by_id):
            event.invalidated = True
            event.save(update_fields=['invalidated'])
            AlertDelivery.objects.filter(kind='group_end', payload__event_id=event.pk,
                status__in=['pending', 'failed']).update(status='cancelled', error='Ending evidence corrected or incomplete.')


def delivery_gate(payload):
    event = GroupAbsenceEnding.objects.select_related('stream').filter(pk=payload.get('event_id')).first()
    if not event or event.invalidated or not evidence_valid(event):
        return 'cancelled'
    if (timezone.now() - event.created_at).total_seconds() > get_config().max_event_age_seconds:
        return 'cancelled'
    state = GroupAbsenceState.objects.get(stream=event.stream, group_id=event.group_id)
    if (not event.stream.enabled or not state.ending_enabled or state.ending_threshold is None
            or event.snapshot['count'] < state.ending_threshold):
        return 'pending'
    return 'ready'
