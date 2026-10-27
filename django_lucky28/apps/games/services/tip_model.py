"""Pure settlement classifier and state machine from Tip Model Documentation v1.

Amounts follow the document's JavaScript safe-integer contract, even in Python.
No participant counts, payout estimates, or rounded percentages classify a round.
"""
from copy import deepcopy
import hashlib
import json

MAX_INTEGER = 2**53 - 1
DEFAULT_THRESHOLDS = (7, 10, 15)
VERSION = 1


def integer(value, minimum=0):
    return type(value) is int and minimum <= value <= MAX_INTEGER


def classify_round(round):
    if not isinstance(round, dict):
        return {'status': 'INVALID', 'reason': 'Round must be an object.'}
    if round.get('settlementFinal') is not True:
        return {'status': 'PENDING', 'reason': 'Waiting for final settlement.'}
    errors = []
    if not isinstance(round.get('gameId'), str) or not round['gameId'].strip():
        errors.append('gameId must be a nonempty string')
    if not integer(round.get('sequence')):
        errors.append('sequence must be a nonnegative safe integer')
    if not integer(round.get('winningNumber')) or round['winningNumber'] > 27:
        errors.append('winningNumber must be from 0 through 27')
    if round.get('totalsComplete') is not True:
        errors.append('whole-round totals are not confirmed complete')
    for field in ('totalBets', 'totalPrizes', 'reportedTip', 'totalUsers', 'winnerCount'):
        if (field in ('totalBets', 'totalPrizes') or field in round) and not integer(round.get(field)):
            errors.append(f'{field} must be a nonnegative safe integer')
    if errors:
        return {'status': 'INVALID', 'reason': '; '.join(errors)}
    if 'totalUsers' in round and round.get('winnerCount', 0) > round['totalUsers']:
        return {'status': 'INVALID', 'reason': 'winnerCount exceeds totalUsers.'}
    tip = round['totalBets'] - round['totalPrizes']
    if tip < 0:
        return {'status': 'INVALID', 'reason': 'Prizes exceed bets; settlement needs reconciliation.'}
    if 'reportedTip' in round and round['reportedTip'] != tip:
        return {'status': 'INVALID', 'reason': 'Reported tip does not match bets minus prizes.'}
    bets = round['totalBets']
    return dict(status='TIP' if tip else 'NO_TIP', tipAmount=tip,
                tipPercent=tip / bets * 100 if bets else 0,
                prizePercent=round['totalPrizes'] / bets * 100 if bets else 0)


def create_state(*, stream_id='lucky28', thresholds=DEFAULT_THRESHOLDS):
    if not isinstance(stream_id, str) or not stream_id.strip():
        raise ValueError('stream_id must be a nonempty string.')
    thresholds = list(thresholds)
    if not thresholds or any(not integer(t, 1) for t in thresholds):
        raise ValueError('Thresholds must be positive safe integers.')
    return dict(version=VERSION, streamId=stream_id, thresholds=sorted(set(thresholds)),
                lastSequence=None, lastGameId=None, lastFingerprint=None,
                noTipStreak=0, lastTipGameId=None, exactStreak=False)


def fingerprint(round):
    fields = ('gameId', 'sequence', 'winningNumber', 'totalBets', 'totalPrizes')
    return hashlib.sha256(json.dumps({k: round[k] for k in fields}, sort_keys=True).encode()).hexdigest()


def advance(state, round, *, emit_alerts=True):
    """Return a new state, diagnostic/classification, and immutable outgoing events."""
    result = classify_round(round)
    updated = deepcopy(state)
    if result['status'] not in ('TIP', 'NO_TIP'):
        return updated, result, []
    sequence, last = round['sequence'], state['lastSequence']
    digest = fingerprint(round)
    if last is not None and sequence <= last:
        status = 'STALE' if sequence < last else 'DUPLICATE' if digest == state['lastFingerprint'] else 'CONFLICT'
        return updated, dict(result, classification=result['status'], status=status), []
    gap = last is not None and sequence != last + 1
    if gap:
        updated.update(noTipStreak=0, exactStreak=False, lastTipGameId=None)
    previous = updated['noTipStreak']
    if result['status'] == 'TIP':
        updated.update(noTipStreak=0, exactStreak=True, lastTipGameId=round['gameId'])
    else:
        updated['noTipStreak'] += 1
    updated.update(lastSequence=sequence, lastGameId=round['gameId'], lastFingerprint=digest)
    result.update(gapDetected=gap, noTipStreak=updated['noTipStreak'], exactStreak=updated['exactStreak'])
    events = []
    kind = 'TIP_GAME' if result['status'] == 'TIP' else 'NO_TIP_STREAK'
    threshold = updated['noTipStreak']
    if emit_alerts and (kind == 'TIP_GAME' or threshold in updated['thresholds']):
        identity = json.dumps([VERSION, state['streamId'], sequence, round['gameId'], kind], separators=(',', ':'))
        event = dict(id=hashlib.sha256(identity.encode()).hexdigest(), type=kind, streamId=state['streamId'],
                     **{k: round[k] for k in ('gameId', 'sequence', 'winningNumber', 'totalBets', 'totalPrizes')}, **result)
        if kind == 'TIP_GAME':
            event.update(previousNoTipStreak=previous,
                         message=f"Tip game {round['gameId']}: result {round['winningNumber']}; tip {result['tipAmount']} diamonds ({result['tipPercent']:.4f}%).")
        else:
            qualifier = '' if updated['exactStreak'] else 'at least '
            event.update(threshold=threshold, lastTipGameId=updated['lastTipGameId'],
                         message=f"No tip for {qualifier}{threshold} consecutive completed games. Latest game: {round['gameId']}.")
        events.append(event)
    return updated, result, events
