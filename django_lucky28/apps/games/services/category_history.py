"""An uninterrupted completed suffix; a gap cannot be counted as a result."""
from games.models import GroupDataIssue
from .group_absence import stream_games, sequence_id, valid_result


def observed_suffix(key):
    games = list(stream_games(key).only('game_no', 'has_winner', 'winning_number', 'status',
                                       'winner_event_ts', 'pre_event_ts', 'created_at'))
    completed = [game for game in games if game.has_winner and game.winner_event_ts]
    if not completed:
        return [], True, True, 'Waiting for completed results.'
    latest = max(completed, key=lambda game: (game.winner_event_ts, game.pk))
    sequence = sequence_id(latest.game_no)
    if sequence is None:
        return [], True, True, 'The latest round ID has no numeric sequence.'
    prefix, end = sequence
    numbered = {}
    for game in games:
        item = sequence_id(game.game_no)
        if not item or item[0] != prefix:
            continue
        if item[1] > end:
            if game.has_winner and not valid_result(game):
                return [], True, True, f'Round {game.game_no} is invalid or has no completion time.'
            continue
        if item[1] in numbered:
            return [], True, True, 'Round IDs have ambiguous sequence numbers.'
        numbered[item[1]] = game
    for issue in GroupDataIssue.objects.filter(stream_id=key):
        item = sequence_id(issue.round_id)
        if item and item[0] == prefix and item[1] >= end:
            saved = numbered.get(item[1])
            if not saved or not valid_result(saved):
                return [], True, True, f'Round {issue.round_id}: {issue.reason}'
    suffix = []
    index = end
    while index in numbered and valid_result(numbered[index]):
        suffix.append(numbered[index])
        index -= 1
    suffix.reverse()
    interrupted = any(number <= index for number in numbered)
    reason = f'History is incomplete before round {suffix[0].game_no}.' if suffix and interrupted else ''
    if not suffix:
        reason = f'Round {latest.game_no} is missing, pending, cancelled or invalid.'
    return suffix, interrupted, not bool(suffix), reason
