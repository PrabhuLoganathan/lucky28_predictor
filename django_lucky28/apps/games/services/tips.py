"""Django adapter for tip-model v1; all state and events commit together."""
from datetime import datetime
import re

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from games.models import GameRound, TipStream, TipRound, TipEvent
from . import tip_model as model


def source_sequence(game_id):
    """Preserve daily gaps without assuming the number of rounds in a day.

    A date change deliberately creates a gap. Only an explicitly supplied global
    sequence can establish continuity across dates. Never count received packets.
    """
    match = re.fullmatch(r'(\d{8})(\d{1,6})', game_id)
    if not match:
        return None
    try:
        day = datetime.strptime(match[1], '%Y%m%d').date()
    except ValueError:
        return None
    return day.toordinal() * 1_000_000 + int(match[2])


def source_round(game, raw=None):
    raw = raw if raw is not None else game.winner_raw
    raw = raw if isinstance(raw, dict) else {}
    # Only use totals captured together in the final packet, never pre-round
    # GameRound.bet_total_energy (which can survive when a winner omits bets).
    round = dict(gameId=game.game_no,
                 sequence=raw.get('settlement_sequence', source_sequence(game.game_no)),
                 winningNumber=raw.get('winning_number', game.winning_number),
                 totalBets=raw.get('bet_total_energy'), totalPrizes=raw.get('win_total_energy'),
                 settlementFinal=game.has_winner and raw.get('status', game.status) in (3, 4)
                    and raw.get('settlement_final', True) is True,
                 totalsComplete=raw.get('totals_complete', True) is True
                    and 'bet_total_energy' in raw and 'win_total_energy' in raw)
    for source, target in (('reported_tip', 'reportedTip'), ('bet_users', 'totalUsers'), ('winner_count', 'winnerCount')):
        if source in raw:
            round[target] = raw[source]
    return round


class TipMonitor:
    """Database-backed equivalent of the document's single-file monitor.

    Construction and dashboard reads are read-only. ingest() acquires the stream
    lock, then persists state, evidence, and outgoing events in one transaction.
    dispatch() holds the same lock through acknowledgment for ordered delivery.
    A crash after external delivery can repeat an event; senders should use its ID.
    """
    def __init__(self, *, stream_id='lucky28', thresholds=None):
        self.stream_id = stream_id
        self.expected = model.create_state(stream_id=stream_id, thresholds=model.DEFAULT_THRESHOLDS if thresholds is None else thresholds)
        self.check_thresholds = thresholds is not None
        saved = TipStream.objects.filter(pk=stream_id).first()
        if saved:
            self._validate(saved.state)

    def _validate(self, state):
        if state.get('version') != model.VERSION or state.get('streamId') != self.stream_id:
            raise ValueError('Saved tip model configuration differs; replay into a new monitor.')
        if self.check_thresholds and state['thresholds'] != self.expected['thresholds']:
            raise ValueError('Saved thresholds differ; replay into a new monitor.')

    def _lock(self):
        TipStream.objects.get_or_create(key=self.stream_id, defaults={'state': self.expected})
        TipStream.objects.filter(pk=self.stream_id).update(revision=F('revision') + 1)
        stream = TipStream.objects.select_for_update().get(pk=self.stream_id)
        self._validate(stream.state)
        return stream

    @transaction.atomic
    def ingest(self, round, *, emit_alerts=True):
        stream = self._lock()
        state, result, events = model.advance(stream.state, round, emit_alerts=emit_alerts)
        if state != stream.state:
            stream.state = state
            stream.save(update_fields=['state', 'updated_at'])
        identity = round.get('gameId') if isinstance(round, dict) else None
        if isinstance(identity, str) and 0 < len(identity) <= 80 and result['status'] not in ('DUPLICATE', 'STALE'):
            sequence = round.get('sequence')
            TipRound.objects.update_or_create(stream=stream, game_id=identity, defaults={
                'sequence': sequence if model.integer(sequence) else None,
                'status': result['status'], 'source': round, 'result': result,
            })
        for event in events:
            TipEvent.objects.get_or_create(pk=event['id'], defaults={'stream': stream, 'payload': event})
        return {'result': result, 'events': events}

    def dispatch(self, send_alert, *, limit=50):
        """Send in order; stop on failure and retain that event for the next pass.

        The callback receives the full event and must raise or return False on
        failure. None is a successful return, matching the document's sender.
        """
        sent = 0
        for _ in range(limit):
            with transaction.atomic():
                stream = self._lock()
                event = stream.events.filter(sent_at__isnull=True).order_by('payload__sequence', 'pk').first()
                if event is None:
                    break
                event.attempts += 1
                try:
                    if send_alert(event.payload) is False:
                        raise RuntimeError('Sender did not acknowledge delivery.')
                except Exception:
                    # Third-party exceptions may contain credentials or URLs.
                    event.last_error = 'Delivery was not acknowledged; queued for retry.'
                    event.save(update_fields=['attempts', 'last_error'])
                    break
                event.sent_at = timezone.now()
                event.last_error = ''
                event.save(update_fields=['attempts', 'sent_at', 'last_error'])
                sent += 1
        return sent


def record_game(game, *, raw=None, emit_alerts=None):
    if game.game_type not in ('lucky28', '', None):
        return None
    if emit_alerts is None:
        observed = game.winner_event_ts
        emit_alerts = bool(observed and not timezone.is_naive(observed)
                           and -5 <= (timezone.now() - observed).total_seconds() <= 120)
    return TipMonitor(stream_id=settings.TIP_MONITOR_ID).ingest(source_round(game, raw), emit_alerts=emit_alerts)


@transaction.atomic
def initialize_history(*, stream_id='lucky28', thresholds=model.DEFAULT_THRESHOLDS):
    """Replay saved evidence, suppressing historical events. Never erase a monitor."""
    monitor = TipMonitor(stream_id=stream_id, thresholds=thresholds)
    stream = monitor._lock()
    if stream.state['lastSequence'] is not None or stream.rounds.exists() or stream.events.exists():
        raise ValueError('Monitor already has history. Choose a new --monitor for a deliberate replay.')
    games = GameRound.objects.filter(
        Q(game_type='lucky28') | Q(game_type='') | Q(game_type__isnull=True), has_winner=True,
    ).only('game_no', 'has_winner', 'status', 'winning_number', 'winner_raw')
    rounds = [source_round(game) for game in games.iterator()]
    rounds.sort(key=lambda row: (row['sequence'] if model.integer(row['sequence']) else -1, row['gameId']))
    counts = {}
    for round in rounds:
        status = monitor.ingest(round, emit_alerts=False)['result']['status']
        counts[status] = counts.get(status, 0) + 1
    return counts


def dashboard(stream_id='lucky28'):
    stream = TipStream.objects.filter(pk=stream_id).first()
    if not stream:
        return dict(state=model.create_state(stream_id=stream_id), rounds=[], events=[], queued=0, totals={})
    from django.db.models import Count
    return dict(state=stream.state,
                rounds=list(stream.rounds.order_by('-sequence', '-pk').values('game_id', 'status', 'source', 'result')[:100]),
                events=list(stream.events.order_by('-created_at', '-pk').values('payload', 'created_at', 'sent_at', 'attempts', 'last_error')[:50]),
                queued=stream.events.filter(sent_at__isnull=True).count(),
                totals={row['status']: row['count'] for row in stream.rounds.values('status').annotate(count=Count('pk'))})
