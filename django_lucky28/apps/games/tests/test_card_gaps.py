from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from PIL import Image

from games.models import GameRound
from games.services.card_gaps import capture_gaps, gap_sections, gap_label
from games.services.card_timeline import snapshot_from_games, snapshot_for_round
from games.services.alert_card import card_model, render_card
from games.services.alert_presentation import format_message
from games.services.group_history import group_statistics


def history(numbers):
    now = timezone.now()
    return [SimpleNamespace(game_no=f'R{len(numbers)-i}', winning_number=n,
        has_winner=True, status=3, winner_event_ts=now-timedelta(minutes=i))
        for i, n in enumerate(numbers)]


class GapCardTests(SimpleTestCase):
    def setUp(self):
        self.games = history([0, 7, 7, 0, 14, 21, 6])
        self.snapshot = snapshot_from_games(self.games)

    def test_current_and_completed_gap_statistics_reuse_dashboard_calculation(self):
        captured = {row['key']: row for row in self.snapshot['gap_analytics']['groups']}
        for row in group_statistics(self.games):
            for field in ('current_gap', 'average_gap', 'max_gap', 'current_incomplete'):
                self.assertEqual(captured[row['key']][field], row[field])
        self.assertEqual(captured['N0']['current_gap'], 0)
        self.assertEqual(captured['N0']['average_gap'], 2)
        self.assertEqual(captured['N0']['max_gap'], 2)
        self.assertEqual(gap_label(captured['N27']), '7+')

    def test_incomplete_intervals_are_not_exact_gaps(self):
        games = history([0, 7, 0])
        games[0].game_no = 'R4'
        rows = {row['key']: row for row in capture_gaps(games)['groups']}
        self.assertEqual(gap_label(rows['N7']), '1*')
        self.assertIsNone(rows['N0']['average_gap'])
        self.assertIsNone(rows['N0']['max_gap'])
        self.assertEqual(gap_label(capture_gaps([])['groups'][0]), 'N/A')

    def test_families_and_generic_rules_select_correct_siblings(self):
        for key, family, length in [('R01','Rows',4), ('C01','Columns',7),
                                     ('SE','Combos',4), ('G04','Colors',7)]:
            sections = gap_sections(dict(group_id=key), 'category', self.snapshot)
            self.assertEqual([(s['family'], len(s['rows'])) for s in sections], [(family,length)])
            self.assertEqual([r['key'] for r in sections[0]['rows'] if r['highlighted']], [key])
        payload = dict(matches=[dict(group='size',values=['Small']), dict(group='parity',values=['Even']),
            dict(group='color',values=['Yellow']), dict(group='number',values=['0']),
            dict(group='extreme',values=['edges'])])
        sections = gap_sections(payload, 'alert', self.snapshot)
        self.assertEqual({s['family'] for s in sections}, {'Size','Parity','Colors','Numbers','Range'})
        self.assertEqual({r['key'] for s in sections for r in s['rows'] if r['highlighted']},
                         {'S','E','G02','N0','edges'})

    def test_window_number_gaps_are_deduplicated_and_legacy_never_invented(self):
        sections = gap_sections(dict(numbers=[0,7,7]), 'window', self.snapshot)
        self.assertEqual([r['key'] for r in sections[0]['rows']], ['N0','N7'])
        self.assertEqual(gap_sections(dict(group_id='R01'), 'category', {}), [])
        self.assertEqual(gap_sections(dict(group_id='R01'), 'health', self.snapshot), [])

    def test_absence_ended_keeps_ended_count_and_zero_current_gap(self):
        payload = dict(game_no='R7', group_id='R01', group_name='Row 1', numbers=list(range(7)),
            mode='absence', change_type='ended', count=2, threshold=2, lower_bound=False,
            ended_number=0, evaluated_round='R7', ended_at='now', stream='lucky28',
            details_path='/round/R7', global_timeline=self.snapshot)
        model = card_model(payload, 'category_end')
        self.assertEqual(model['count'], '2')
        self.assertEqual(model['gap_sections'][0]['rows'][0]['current_gap'], 0)
        self.assertIn('Gap analytics (observed rounds): Row 1: 0', format_message(payload, 'category_end'))
        output = render_card(payload, 'category_end')
        self.assertLess(len(output), 400000)
        self.assertEqual(Image.open(BytesIO(output)).width, 1080)


class FrozenGapTests(TestCase):
    def test_full_history_is_anchored_and_render_does_not_read_database(self):
        games = history([0]+[7]*200+[0])
        GameRound.objects.bulk_create([GameRound(game_no=g.game_no, winning_number=g.winning_number,
            winner_event_ts=g.winner_event_ts, has_winner=True, status=3, game_type='lucky28') for g in games])
        snapshot = snapshot_for_round('lucky28', 'R201')
        self.assertEqual(snapshot['gap_analytics']['history_count'], 201)
        self.assertEqual(snapshot['gap_analytics']['as_of'], 'R201')
        row = next(r for r in snapshot['gap_analytics']['groups'] if r['key']=='R01')
        self.assertEqual(row['current_gap'], 200)
        self.assertFalse(row['gap_lower_bound'])
        payload = dict(group_id='R01', mode='absence', count=200, global_timeline=snapshot)
        original = render_card(payload, 'category')
        GameRound.objects.filter(game_no='R201').update(winning_number=0)
        with self.assertNumQueries(0):
            self.assertEqual(render_card(payload, 'category'), original)
