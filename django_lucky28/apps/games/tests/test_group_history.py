from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from games.models import GameRound
from games.services.timeline import build_timeline


class GroupHistoryTests(TestCase):
    def result(self, index, number, **kwargs):
        values = dict(game_no=f'R{index}', game_type='lucky28', winning_number=number,
                      has_winner=True, status=3,
                      winner_event_ts=timezone.now() + timedelta(seconds=index))
        values.update(kwargs)
        return GameRound.objects.create(**values)

    def groups(self):
        return {g['key']: g for g in build_timeline('lucky28', [])['group_stats']}

    def test_group_hit_resets_on_any_member_and_zero_is_valid(self):
        for i, number in enumerate([0, 6, 14, 3, 7, 21]):
            self.result(i, number)
        groups = self.groups()
        row = groups['R01']
        self.assertEqual(row['current_gap'], 2)
        self.assertEqual([h['gap'] for h in row['history']], [1, 0])
        self.assertEqual((row['average_gap'], row['max_gap']), (0.5, 1))
        self.assertEqual(groups['C01']['current_gap'], 0)  # 0, 7, 14, 21
        self.assertEqual(groups['C01']['total_hits'], 4)
        self.assertEqual(groups['G04']['current_gap'], 0)  # blue: 6, 7, 20, 21
        self.assertEqual(groups['S']['current_gap'], 1)
        self.assertEqual(groups['BO']['current_gap'], 0)
        self.assertEqual(groups['E']['current_gap'], 3)
        self.assertEqual(groups['SE']['current_gap'], 4)
        self.assertEqual(groups['edges']['current_gap'], 2)
        self.assertEqual(groups['middle']['current_gap'], 0)
        for family in ('Rows', 'Columns', 'Size', 'Parity', 'Combos', 'Colors', 'Range'):
            self.assertEqual(sum(g['recent_hits'] for g in groups.values() if g['family'] == family), 6)

    def test_empty_and_unseen_are_different_from_zero_and_one_hit_has_no_average(self):
        self.assertTrue(all(g['current_gap'] is None for g in self.groups().values()))
        self.result(1, 0)
        groups = self.groups()
        self.assertEqual(groups['SE']['current_gap'], 0)
        self.assertIsNone(groups['SE']['average_gap'])
        self.assertEqual(groups['B']['current_gap'], 1)
        self.assertTrue(groups['B']['gap_lower_bound'])
        self.assertIsNone(groups['B']['latest_appearance'])
        self.assertEqual(groups['B']['history'], [])

    def test_unverified_intervals_are_marked_and_excluded_from_average(self):
        for i, number in [(0, 0), (1, 14), (2, 1), (4, 14), (5, 2), (7, 14)]:
            self.result(i, number)
        small = self.groups()['S']
        self.assertEqual(small['current_gap'], 1)
        self.assertTrue(small['current_incomplete'])
        self.assertEqual([h['incomplete'] for h in small['history']], [True, False])
        self.assertEqual(small['exact_gap_count'], 1)
        self.assertEqual(small['average_gap'], 1)

    def test_full_history_corrections_streams_and_reset_independence(self):
        self.result(0, 0)
        for i in range(1, 155):
            self.result(i, 14)
        self.result(155, 0, has_winner=False)
        self.result(156, 0, status=2)
        self.result(157, 0, game_type='other')
        self.client.post('/api/trackers/size/reset/')
        groups = self.groups()
        self.assertEqual(groups['S']['current_gap'], 154)
        self.assertEqual(groups['S']['latest_appearance']['game_no'], 'R0')
        GameRound.objects.filter(game_no='R154').update(winning_number=0)
        small = self.groups()['S']
        self.assertEqual(small['current_gap'], 0)
        self.assertEqual(small['history'][0]['gap'], 153)
        self.assertEqual(small['history'][0]['start']['game_no'], 'R0')
        self.assertEqual(small['history'][0]['end']['game_no'], 'R154')
        big = self.groups()['B']
        self.assertEqual(len(big['history']), 30)
        self.assertEqual(big['completed_gap_count'], 152)
        response = self.client.get('/api/trackers/live/?tracks=')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['group_stats']), 28)

    def test_current_streaks_reset_and_stop_at_unknown_boundaries(self):
        for i, number in enumerate([14, 5, 7, 9]):
            self.result(i, number)
        groups = self.groups()
        for key in ('S', 'O', 'SO'):
            self.assertEqual(groups[key]['current_streak'], 3)
            self.assertFalse(groups[key]['streak_lower_bound'])
            self.assertFalse(groups[key]['streak_incomplete'])
        self.result(4, 16)
        for key in ('S', 'O', 'SO'):
            self.assertEqual(self.groups()[key]['current_streak'], 0)
        self.result(6, 18)  # Missing R5: cannot join 18 and 16 into a verified run.
        even = self.groups()['E']
        self.assertEqual(even['current_streak'], 1)
        self.assertTrue(even['streak_incomplete'])
        self.assertFalse(even['streak_lower_bound'])
        self.result(5, 20)  # A late import repairs the run from the same history.
        even = self.groups()['E']
        self.assertEqual(even['current_streak'], 3)
        self.assertFalse(even['streak_incomplete'])
        GameRound.objects.filter(game_no='R5').update(winning_number=19)
        self.assertEqual(self.groups()['E']['current_streak'], 1)

    def test_history_limited_and_missing_latest_streaks(self):
        self.assertIsNone(self.groups()['S']['current_streak'])
        self.result(0, 0)
        self.result(1, 2)
        group = self.groups()['SE']
        self.assertEqual(group['current_streak'], 2)
        self.assertTrue(group['streak_lower_bound'])
        self.result(2, None, has_winner=False, status=2)  # Active round is not a missing result.
        self.assertEqual(self.groups()['SE']['current_streak'], 2)
        GameRound.objects.filter(game_no='R2').update(status=3)
        self.assertTrue(all(g['current_streak'] is None for g in self.groups().values()))
        GameRound.objects.filter(game_no='R2').update(winning_number=3, has_winner=True)
        self.assertEqual(self.groups()['SE']['current_streak'], 0)
        self.assertEqual(self.groups()['S']['current_streak'], 3)
