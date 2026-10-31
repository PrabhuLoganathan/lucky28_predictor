"""Recheck recipient choices before sending queued alerts."""
from games.models import AlertRule, GroupAbsenceState


def permits_route(destination, send_to_levels, destination_ids=(), minimum=1):
    return (destination.pk in destination_ids or
            (send_to_levels and destination.routing_type == 'level' and destination.plan_rank >= minimum))


def owner_permits(owner, destination, minimum=1):
    return permits_route(destination, owner.send_to_levels,
                         [d.pk for d in owner.destinations.all()], minimum)


def routing_allowed(delivery):
    destination, payload = delivery.destination, delivery.payload
    if delivery.kind == 'test':
        return True  # Explicit operator action.
    if delivery.kind in ('group', 'group_end'):
        state = GroupAbsenceState.objects.prefetch_related('destinations').filter(stream_id=payload.get('stream'),
            group_id=payload.get('group_id')).first()
        return bool(state and owner_permits(state, destination))
    if delivery.kind == 'result':
        if not delivery.evaluation_id:
            return False
        return any(routing_allowed(original) for original in delivery.evaluation.deliveries.filter(
            destination=destination, kind='alert', status='sent').select_related('destination'))
    if delivery.kind == 'alert':
        for match in payload.get('matches', []):
            minimum = match.get('min_plan_rank', 1)
            if match.get('rule_key'):
                rule = AlertRule.objects.prefetch_related('destinations').filter(key=match['rule_key']).first()
                if not rule or not rule.enabled or not owner_permits(rule, destination, max(minimum, rule.min_plan_rank)):
                    return False
            else:
                # Older payloads without a rule reference retain their saved routing.
                target = match.get('direct_destination_id')
                ids = match.get('destination_ids', [target] if target is not None else [])
                if not permits_route(destination, match.get('send_to_levels', target is None), ids, minimum):
                    return False
        return bool(payload.get('matches'))
    return permits_route(destination, True, minimum=
        max((match.get('min_plan_rank', 1) for match in payload.get('matches', [])), default=1))
