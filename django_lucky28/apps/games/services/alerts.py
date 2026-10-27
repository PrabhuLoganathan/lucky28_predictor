"""Freeze evidence at ingestion and enqueue notifications in the same transaction."""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from games.models import (GameRound, AlertRule, AlertEvaluation, AlertOccurrence,
                          AlertDestination, AlertDelivery, AlertRuntime)
from .analysis import AnalysisService
from .alert_engine import evaluate_rules
from .alert_settings import get_config


def locked_runtime():
    AlertRuntime.objects.get_or_create(pk=1)
    # UPDATE acquires SQLite's write lock; SELECT FOR UPDATE alone does not.
    AlertRuntime.objects.filter(pk=1).update(version=F('version') + 1)
    return AlertRuntime.objects.select_for_update().get(pk=1)


def eligible_destinations(now):
    return AlertDestination.objects.filter(enabled=True).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))


def game_facts(history):
    return {
        'size': [g.size_label for g in history],
        'parity': [g.parity_label for g in history],
        'color': [AnalysisService.get_color(g.winning_number) for g in history],
        'number': [str(g.winning_number) for g in history],
    }


def result_snapshot(game):
    return dict(game_no=game.game_no, number=game.winning_number, size=game.size_label,
                parity=game.parity_label, color=AnalysisService.get_color(game.winning_number),
                observed_at=game.winner_event_ts.isoformat() if game.winner_event_ts else None)


def queue_delivery(key, destination, kind, payload, evaluation=None):
    return AlertDelivery.objects.get_or_create(dedup_key=key, defaults={
        'destination': destination, 'evaluation': evaluation, 'kind': kind,
        'payload': dict(payload, chat_id=destination.chat_id, use_cards=destination.use_cards),
    })[0]


@transaction.atomic
def record_live_event(game, phase):
    # Legacy endpoints may assign timestamp/number strings to the model instance.
    game.refresh_from_db()
    from .group_absence import synchronize, stream_key
    synchronize(stream_key(game))
    from .window_alerts import synchronize as synchronize_windows
    synchronize_windows(stream_key(game))
    from .category_alerts import synchronize as synchronize_categories
    synchronize_categories(stream_key(game))
    if game.game_type not in (None, '', 'lucky28'):
        return None
    observed = game.pre_event_ts if phase == 'pre' else game.winner_event_ts
    if isinstance(observed, str):
        observed = parse_datetime(observed)
    now = timezone.now()
    config = get_config()
    # Replayed/historical packets cannot reconstruct what was known pre-result.
    if observed is None or timezone.is_naive(observed) or not -5 <= (now - observed).total_seconds() <= config.max_event_age_seconds:
        return None
    runtime = locked_runtime()
    if runtime.last_observed_at is None or observed > runtime.last_observed_at:
        runtime.last_received_at = now
        runtime.last_observed_at = observed
        runtime.outage_active = False
        runtime.save()
    if phase == 'winner':
        queue_results(game, now)
        return None
    game = GameRound.objects.select_for_update().get(pk=game.pk)
    existing = AlertEvaluation.objects.filter(game=game).first()
    if existing:
        return existing
    if game.has_winner:
        return None
    # An older round arriving after a newer pre-round must not alter active state.
    if AlertEvaluation.objects.filter(observed_at__gte=observed).exists():
        return None
    completed = GameRound.objects.filter(
        has_winner=True, winning_number__gte=0, winning_number__lte=27,
        winner_event_ts__lt=observed,
    ).filter(Q(game_type='lucky28') | Q(game_type__isnull=True) | Q(game_type='')).exclude(pk=game.pk)
    history = list(completed.order_by('-winner_event_ts', '-pk')[:settings.ALERT_HISTORY_LIMIT])
    totals = {str(row['winning_number']): row['total'] for row in
              completed.values('winning_number').annotate(total=Count('pk'))}
    session_start = settings.SERVER_SESSION_STARTED_AT
    session_history = [g for g in history if g.winner_event_ts >= session_start]
    facts, session_facts = game_facts(history), game_facts(session_history)
    previous = AlertEvaluation.objects.order_by('-observed_at', '-pk').first()
    prior = previous.active_keys if previous else []
    matches = []
    for rule in AlertRule.objects.filter(enabled=True).order_by('key'):
        active = prior if not rule.session_only or (previous and previous.session_started_at == session_start) else []
        matches.extend(evaluate_rules([rule], session_facts if rule.session_only else facts, active))
    from .card_timeline import snapshot_from_games
    evidence = dict(version=1, game_no=game.game_no, reference=f'alert-{game.pk}',
                    global_timeline=snapshot_from_games(history),
                    captured_at=now.isoformat(), observed_at=observed.isoformat(),
                    session_started_at=session_start.isoformat(), history_count=len(history),
                    history_limit=settings.ALERT_HISTORY_LIMIT,
                    lifetime_totals=dict(completed=sum(totals.values()), numbers=totals),
                    rates={f: str(getattr(game, f)) if getattr(game, f) is not None else None
                           for f in ('rate_big', 'rate_small', 'rate_odd', 'rate_even')},
                    timeline=[result_snapshot(g) for g in history[:50]],
                    previous_results=[result_snapshot(g) for g in history[:6]], matches=matches)
    evaluation = AlertEvaluation.objects.create(game=game, game_no=game.game_no, observed_at=observed,
        captured_at=now, session_started_at=session_start, active_keys=[m['identity'] for m in matches], evidence=evidence)
    AlertOccurrence.objects.bulk_create([AlertOccurrence(evaluation=evaluation, identity=m['identity'],
        rule_key=m['rule_key'], is_activation=m['is_activation'], snapshot=m) for m in matches])
    if config.telegram_enabled:
        for destination in eligible_destinations(now):
            routed = [m for m in matches if m['is_activation'] and m['min_plan_rank'] <= destination.plan_rank]
            for match in routed:
                queue_delivery(f'alert:{evaluation.pk}:{destination.pk}:{match["identity"]}', destination, 'alert',
                               dict(evidence, matches=[match]), evaluation)
    return evaluation


def queue_results(game, now):
    if not get_config().telegram_enabled:
        return
    evaluation = AlertEvaluation.objects.filter(game=game).first()
    if not evaluation:
        return
    from .card_timeline import snapshot_for_round
    global_timeline = snapshot_for_round(game.game_type or 'lucky28', game.game_no)
    for original in evaluation.deliveries.filter(kind='alert', status__in=['pending', 'sending', 'sent']).select_related('destination'):
        destination = original.destination
        if destination.enabled and destination.send_results and (not destination.expires_at or destination.expires_at > now):
            queue_delivery(f'result:{evaluation.pk}:{destination.pk}', destination, 'result',
                           dict(game_no=game.game_no, captured_at=now.isoformat(), result=result_snapshot(game),
                                reference=evaluation.evidence['reference'], matches=[], global_timeline=global_timeline), evaluation)


@transaction.atomic
def check_collection_health(now=None):
    now = now or timezone.now()
    config = get_config()
    runtime = locked_runtime()
    runtime.heartbeat_at = now
    runtime.worker_status = 'running'
    if not config.telegram_enabled:
        runtime.monitoring_started_at = None
        runtime.outage_active = False
        runtime.save()
        return
    if runtime.monitoring_started_at is None:
        runtime.monitoring_started_at = now
        runtime.outage_active = False
    anchor = max(runtime.monitoring_started_at, runtime.last_received_at or runtime.monitoring_started_at)
    if not runtime.outage_active and now - anchor >= timedelta(minutes=config.collection_timeout_minutes):
        runtime.outage_active = True
        runtime.outage_number += 1
        for destination in eligible_destinations(now).filter(send_health=True):
            queue_delivery(f'health:{runtime.outage_number}:{destination.pk}', destination, 'health',
                           dict(game_no='Collection stopped', captured_at=now.isoformat(), matches=[],
                                outage_number=runtime.outage_number,
                                detail=f'No fresh Lucky28 events for {int((now - anchor).total_seconds() // 60)} minutes.'))
    runtime.save()
