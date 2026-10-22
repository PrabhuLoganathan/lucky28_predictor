from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase
from django.utils import timezone

from games.models import (GameRound, GroupAbsenceStream, GroupAbsenceEvent, CategoryAlertSettings,
                          CategoryAlertRule, CategoryAlertEvent, WindowAlertEvent,
                          AlertEvaluation, AlertOccurrence, AlertDelivery)
from games.services.timeline import build_timeline, classify, recent_games, TRACKS


class TimelineTests(TestCase):
    def setUp(self):
        self.base = timezone.now() - timedelta(hours=3)

    def result(self, index, number, **kwargs):
        values = dict(game_no=f'R{index}', game_type='lucky28', winning_number=number,
                      has_winner=True, status=3, winner_event_ts=self.base + timedelta(seconds=index))
        values.update(kwargs)
        return GameRound.objects.create(**values)

    def sequence(self, numbers, start=0):
        return [self.result(i, n) for i, n in enumerate(numbers, start)]

    def track(self, data, key):
        return next(t for t in data['tracks'] if t['tracker_key'] == key)

    def test_150_results_newest_first_cross_dates_and_oldest_context(self):
        self.base = timezone.now().replace(hour=23, minute=59, second=0, microsecond=0) - timedelta(days=1)
        self.sequence([i % 28 for i in range(160)])
        self.result(161, 9, has_winner=False)
        self.result(162, 28)
        self.result(163, 2, status=2)
        self.result(164, 1, winner_event_ts=None)
        self.result(165, 7, game_type='other')
        data = build_timeline('lucky28')
        self.assertEqual(len(data['games']), 150)
        self.assertEqual(data['latest_game_id'], 'R159')
        self.assertEqual(data['games'][-1]['game_no'], 'R10')
        self.assertNotEqual(data['games'][0]['timestamp'][:10], data['games'][-1]['timestamp'][:10])
        self.assertEqual(len(data['tracks']), len(TRACKS))
        self.assertEqual(self.track(data, 'window')['timeline'][-1]['letter'], 'D')
        self.assertFalse(data['has_gaps'])
        self.assertEqual(AlertDelivery.objects.count(), 0)

    def test_number_game_mappings_cover_every_number(self):
        self.sequence(range(28))
        games = recent_games('lucky28')
        for i, game in enumerate(games):
            n = game.winning_number
            self.assertEqual(classify('size', games, i), 'S' if n < 14 else 'B')
            self.assertEqual(classify('parity', games, i), 'E' if n % 2 == 0 else 'O')
            self.assertEqual(classify('row', games, i), f'R{n // 7 + 1}')
            self.assertEqual(classify('column', games, i), f'C{n % 7 + 1}')
            self.assertEqual(classify('extreme', games, i), 'J' if n < 6 or n > 21 else 'M')
        data = build_timeline('lucky28')
        self.assertEqual(self.track(data, 'combo')['timeline'][0]['letter'], 'BO')
        self.assertEqual(self.track(data, 'color')['timeline'][0]['letter'], 'G1')
        self.assertEqual(self.track(data, 'color')['timeline'][13]['letter'], 'G7')

    def test_repeat_and_window_warmup_and_old_repeat(self):
        self.sequence([8, 8, 1, 2, 3, 4, 5, 6, 7, 9])
        data = build_timeline('lucky28', ['repeat', 'window'])
        self.assertEqual(self.track(data, 'repeat')['timeline'][0]['letter'], 'N')
        self.assertEqual(self.track(data, 'repeat')['timeline'][-2]['letter'], '?')
        self.assertEqual(self.track(data, 'window')['timeline'][0]['letter'], 'R')
        self.assertEqual(self.track(data, 'window')['timeline'][1]['letter'], '?')
        self.result(10, 9)
        self.assertEqual(self.track(build_timeline('lucky28', ['repeat']), 'repeat')['timeline'][0]['letter'], 'R')

    def test_gaps_do_not_create_streaks_or_repeat_windows(self):
        self.sequence([1] * 10)
        self.result(11, 1)
        self.result(12, 1)
        data = build_timeline('lucky28')
        self.assertTrue(data['has_gaps'])
        self.assertEqual(self.track(data, 'repeat')['timeline'][0]['letter'], '?')
        self.assertEqual(self.track(data, 'window')['timeline'][0]['letter'], '?')
        self.assertEqual(self.track(data, 'size')['active_events'], [])
        self.sequence([1] * 10, start=13)
        self.assertEqual(self.track(build_timeline('lucky28'), 'window')['timeline'][0]['letter'], 'R')

    def test_patterns_streak_absence_density_and_alternating(self):
        self.sequence([1] * 10)
        events = self.track(build_timeline('lucky28', ['size']), 'size')['active_events']
        self.assertEqual({e['id'].split('-')[0] for e in events}, {'streak', 'absence', 'density'})
        self.sequence([14, 1, 14, 1], start=10)
        events = self.track(build_timeline('lucky28', ['size']), 'size')['active_events']
        self.assertTrue(any(e['id'].startswith('alternating') for e in events))

    def test_saved_alert_sources_and_category_endings(self):
        game = self.result(100, 3)
        stream = GroupAbsenceStream.objects.get(pk='lucky28')
        evaluation = AlertEvaluation.objects.create(game=game, game_no=game.game_no, observed_at=self.base,
            session_started_at=self.base)
        AlertOccurrence.objects.create(evaluation=evaluation, identity='test', rule_key='test', is_activation=True,
            snapshot={'title': 'Rule alert', 'detail': 'Recorded evidence'})
        GroupAbsenceEvent.objects.create(stream=stream, group_id='G01', period_key='one',
            snapshot={'evaluated_round': game.game_no, 'color': 'Red', 'absence': 10})
        config = CategoryAlertSettings.objects.create(stream=stream)
        rule = CategoryAlertRule.objects.create(settings=config, group_id='R01', mode='streak')
        CategoryAlertEvent.objects.create(rule=rule, period_key='one', snapshot={'evaluated_round': 'R99'},
            resolution_snapshot={'evaluated_round': game.game_no, 'group_name': 'Row 1', 'mode': 'streak', 'count': 4})
        WindowAlertEvent.objects.create(stream=stream, kind='repeat', occurrence_key='one', snapshot={'end_round': game.game_no})
        WindowAlertEvent.objects.create(stream=stream, kind='repeat', occurrence_key='invalid',
            invalidated_at=timezone.now(), snapshot={'end_round': game.game_no})
        data = build_timeline('lucky28', ['alerts'])
        self.assertEqual(len(data['games'][0]['alerts']), 4)
        self.assertEqual(self.track(data, 'alerts')['timeline'][0]['letter'], 'A')
        titles = [event['title'] for event in data['games'][0]['alerts']]
        self.assertIn('Row 1 streak ended', titles)
        self.assertIn('Red absence', titles)

    def test_reset_is_post_only_csrf_protected_and_session_and_stream_isolated(self):
        self.sequence([1, 2, 3])
        self.result(3, 2, game_type='other')
        url = '/api/trackers/size/reset/'
        self.assertEqual(self.client.get(url).status_code, 405)
        protected = Client(enforce_csrf_checks=True)
        self.assertEqual(protected.post(url).status_code, 403)
        protected.get('/alerts/timeline/')
        response = protected.post(url, HTTP_X_CSRFTOKEN=protected.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)
        data = protected.get('/api/trackers/live/').json()
        self.assertEqual(self.track(data, 'size')['timeline'], [])
        self.assertEqual(len(self.track(data, 'parity')['timeline']), 3)
        self.assertEqual(len(self.track(self.client.get('/api/trackers/live/').json(), 'size')['timeline']), 3)
        self.assertEqual(len(self.track(protected.get('/api/trackers/live/?stream=other').json(), 'size')['timeline']), 1)
        self.result(4, 14)
        # Backfilled history older than the reset should stay hidden.
        self.result(1, 8, game_no='old1', winner_event_ts=self.base - timedelta(days=1))
        data = protected.get('/api/trackers/live/').json()
        self.assertEqual([i['game_no'] for i in self.track(data, 'size')['timeline']], ['R4'])
        protected.post(url, {'action': 'restore'}, HTTP_X_CSRFTOKEN=protected.cookies['csrftoken'].value)
        self.assertEqual(len(self.track(protected.get('/api/trackers/live/').json(), 'size')['timeline']), 5)

    def test_disabled_tracks_omit_expensive_alert_queries(self):
        self.result(1, 3)
        with patch('games.services.timeline.recorded_alerts') as evidence:
            data = self.client.get('/api/trackers/live/?tracks=size,parity').json()
            evidence.assert_not_called()
        self.assertEqual([t['tracker_key'] for t in data['tracks']], ['size', 'parity'])
        self.assertEqual(self.client.get('/api/trackers/live/?tracks=').json()['tracks'], [])
        self.assertEqual(self.client.get('/api/trackers/live/?tracks=bad').status_code, 400)
        self.assertEqual(self.client.get('/api/trackers/live/?stream=bad').status_code, 400)
        self.assertEqual(self.client.post('/api/trackers/bad/reset/').status_code, 400)

    def test_empty_and_page_integration(self):
        data = self.client.get('/api/trackers/live/').json()
        self.assertEqual(data['games'], [])
        self.assertIsNone(data['latest_game_id'])
        self.assertContains(self.client.get('/alerts/timeline/'), 'Global alert timeline')
        self.assertContains(self.client.get('/analysis/'), 'Global alert timeline')

    def test_poll_sees_new_results_and_corrections_without_writes(self):
        self.result(1, 0)
        first = self.client.get('/api/trackers/live/?tracks=size').json()
        self.assertEqual(self.track(first, 'size')['timeline'][0]['letter'], 'S')
        GameRound.objects.filter(game_no='R1').update(winning_number=27)
        second = self.client.get('/api/trackers/live/?tracks=size').json()
        self.assertEqual(self.track(second, 'size')['timeline'][0]['letter'], 'B')
        self.result(2, 5)
        third = self.client.get('/api/trackers/live/?tracks=size').json()
        self.assertEqual(third['latest_game_id'], 'R2')
        self.assertEqual(AlertEvaluation.objects.count(), 0)
        self.assertEqual(AlertDelivery.objects.count(), 0)
