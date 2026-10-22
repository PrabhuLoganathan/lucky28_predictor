from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from games.models import GameRound
from games.services.timeline import build_timeline


class NumberPaletteTests(TestCase):
    def setUp(self):
        self.base = timezone.now() - timedelta(hours=1)

    def result(self, index, number, **kwargs):
        values = dict(game_no=f'R{index}', game_type='lucky28', winning_number=number,
            has_winner=True, status=3, winner_event_ts=self.base + timedelta(seconds=index))
        values.update(kwargs)
        return GameRound.objects.create(**values)

    def feed(self):
        return build_timeline('lucky28', [])

    def test_rolling_duplicates_remain_until_last_appearance_leaves(self):
        for i,n in enumerate([2,5,2,14,9,5,20,1,14,7]): self.result(i,n)
        data = self.feed()
        self.assertEqual({s['number'] for s in data['number_stats'] if s['hits']}, {1,2,5,7,9,14,20})
        self.assertEqual(data['number_stats'][2]['hits'], 2)
        self.result(10,11)
        data = self.feed()
        self.assertEqual(data['number_stats'][2]['hits'], 1)
        self.assertEqual(data['number_stats'][11]['hits'], 1)
        self.result(11,0)
        self.result(12,9)
        data = self.feed()
        self.assertEqual(data['number_stats'][2]['hits'], 0)
        self.assertEqual(data['number_stats'][0]['hits'], 1)
        self.assertEqual(sum(s['hits'] for s in data['number_stats']), 10)

    def test_corrections_rebuild_counts_and_live_gaps_from_identical_source(self):
        for i,n in enumerate([0,3,0,4,3,0]): self.result(i,n)
        self.result(6,27,has_winner=False)
        self.result(7,27,status=2)
        self.result(8,27,game_type='other')
        data = self.client.get('/api/trackers/live/?tracks=').json()
        self.assertEqual(len(data['games']), 6)
        zero = data['number_stats'][0]
        self.assertEqual((zero['hits'], zero['current_gap'], zero['max_gap'], zero['average_gap']), (3,0,2,1.5))
        self.assertIsNone(data['number_stats'][4]['average_gap'])
        GameRound.objects.filter(game_no='R5').update(winning_number=3)
        data = self.client.get('/api/trackers/live/?tracks=').json()
        self.assertEqual(data['number_stats'][0]['hits'], 2)
        self.assertEqual(data['number_stats'][0]['current_gap'], 3)
        gaps = self.client.get('/api/gaps/').json()
        self.assertEqual(gaps['stats'], data['number_stats'])
        self.assertEqual(gaps['latest_game_id'], data['latest_game_id'])
        GameRound.objects.filter(game_no='R5').delete()
        self.assertEqual(self.feed()['number_stats'][3]['hits'], 2)

    def test_late_packet_order_is_round_order_and_missing_rounds_are_observed_only(self):
        self.result(8,2)
        self.result(10,4)
        self.result(9,0,winner_event_ts=self.base+timedelta(minutes=10))
        self.assertEqual([g['game_no'] for g in self.feed()['games']], ['R10','R9','R8'])
        self.assertEqual(self.feed()['number_stats'][0]['current_gap'], 1)

    def test_latest_appearance_outside_150_and_empty_history(self):
        data = self.feed()
        self.assertEqual(data['observed_games'], 0)
        self.assertTrue(all(s['current_gap'] is None for s in data['number_stats']))
        self.result(0,27)
        for i in range(1,155): self.result(i,i%5)
        data = self.feed()
        self.assertEqual(len(data['games']),150)
        self.assertEqual(data['number_stats'][27]['latest_appearance']['game_no'],'R0')
        self.assertEqual(data['number_stats'][27]['current_gap'],154)
        self.assertEqual(data['number_stats'][26]['current_gap'],155)
        self.assertTrue(data['number_stats'][26]['gap_lower_bound'])
        self.assertIsNone(data['number_stats'][26]['latest_appearance'])

    def test_hidden_tracks_and_reset_do_not_clear_palette(self):
        self.result(1,0)
        self.client.post('/api/trackers/number/reset/')
        data = self.client.get('/api/trackers/live/?tracks=number').json()
        self.assertEqual(data['tracks'][0]['timeline'], [])
        self.assertEqual(data['number_stats'][0]['hits'], 1)
        self.assertEqual(self.client.get('/api/gaps/?stream=bad').status_code,400)
