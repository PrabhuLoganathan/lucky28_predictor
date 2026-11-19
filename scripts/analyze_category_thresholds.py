"""Read-only absence-run analysis. Run through manage.py shell.

Gaps break runs. Leading censored runs are excluded; trailing observed runs
are included. Rates describe this sample and are not future delivery forecasts.
"""
import json
from games.services.group_absence import stream_games, sequence_id, valid_result
from games.category_config import EXTREME_GROUPS, BORDER_GROUPS
segments=[]
current=[]
previous=None
for game in stream_games('lucky28').order_by('game_no'):
    seq=sequence_id(game.game_no)
    consecutive=previous and seq and seq[0]==previous[0] and seq[1]==previous[1]+1
    if not valid_result(game) or not consecutive:
        if current: segments.append(current)
        current=[]
    if valid_result(game): current.append(game.winning_number)
    previous=seq if valid_result(game) else None
if current: segments.append(current)
n=sum(map(len,segments))
report={'valid_rounds':n,'segments':len(segments),'segments_at_least_50':sum(len(s)>=50 for s in segments),'longest_segment':max(map(len,segments)), 'target':'At most one historical absence activation per 1000 valid rounds per group. Streak alerts disabled to avoid duplicate complementary alerts.', 'groups':{}}
for group in EXTREME_GROUPS+BORDER_GROUPS:
    runs=[]
    for segment in segments:
        seen_member=False
        run=0
        for number in segment:
            if number in group.numbers:
                if seen_member and run: runs.append(run)
                seen_member=True
                run=0
            elif seen_member: run+=1
        if seen_member and run: runs.append(run)
    candidates={str(t):sum(r>=t for r in runs) for t in range(3,201)}
    threshold=next((t for t in range(3,201) if candidates[str(t)]<=n/1000),200)
    report['groups'][group.id]={'name':group.name,'absence_threshold':threshold,'historical_activations':candidates[str(threshold)],'activations_per_1000_rounds':round(candidates[str(threshold)]/n*1000,2),'candidates':candidates}
print(json.dumps(report,indent=2))
