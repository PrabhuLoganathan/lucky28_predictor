from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from games.models import GameRound, SignalLog, SignalRule


@override_settings(LOGGER_API_TOKEN='logger-test-token', TIME_ZONE='UTC')
class LoggerApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.credentials(HTTP_X_LUCKY28_TOKEN='logger-test-token')

    def event(self, game_no='round-1', phase='pre', observed='2026-09-07T23:59:50Z', **data):
        payload = {
            'schema_version': 1, 'game_type': 'lucky28', 'game_no': game_no,
            'phase': phase, 'observed_at': observed, 'data': data,
        }
        return self.client.post('/api/logger/events/', payload, format='json')

    def test_health_requires_shared_token(self):
        self.assertEqual(self.client.get('/api/logger/health/').data['service'], 'lucky28')
        self.client.credentials(HTTP_X_LUCKY28_TOKEN='wrong')
        self.assertEqual(self.client.get('/api/logger/health/').status_code, 403)
        self.assertEqual(self.event().status_code, 403)
        self.assertEqual(GameRound.objects.count(), 0)

    def test_pre_rates_and_winner_zero_are_saved_with_utc_timestamps(self):
        response = self.event(rate_big=43.25, latest_statistic='2B/1E', surplus_seconds=10)
        self.assertEqual(response.status_code, 200)
        response = self.event(phase='winner', observed='2026-09-08T00:00:01Z', winning_number=0,
                              status=3, reward_numbers=[0, 0, 0], winner_count=0, win_total_energy=0)
        self.assertEqual(response.status_code, 200)
        game = GameRound.objects.get()
        self.assertTrue(game.has_pre and game.has_winner)
        self.assertEqual(game.game_type, 'lucky28')
        self.assertEqual(game.rate_big, Decimal('43.25'))
        self.assertEqual(game.winning_number, 0)
        self.assertEqual(game.reward_type, 'Small/Even')
        self.assertEqual(game.winner_event_ts, datetime(2026, 9, 8, 0, 0, 1, tzinfo=timezone.utc))
        self.assertEqual(self.client.get('/history/?date=2026-09-08').context['day_summary']['total'], 1)

    def test_winner_can_arrive_before_pre(self):
        self.assertEqual(self.event(phase='winner', winning_number=14, status=3, bet_users=20).status_code, 200)
        self.assertEqual(self.event(rate_big=10, bet_users=10).status_code, 200)
        game = GameRound.objects.get()
        self.assertTrue(game.has_winner and game.has_pre)
        self.assertEqual(game.winning_number, 14)
        self.assertEqual(game.bet_users, 20)

    def test_late_pre_packet_cannot_replace_newer_rates(self):
        self.event(observed='2026-09-07T23:59:55Z', rate_big=75)
        response = self.event(observed='2026-09-07T23:59:50Z', rate_big=10)
        self.assertTrue(response.data['duplicate'])
        self.assertEqual(GameRound.objects.get().rate_big, 75)

    def test_retried_winner_keeps_original_day(self):
        self.event(phase='winner', winning_number=19, status=3)
        response = self.event(phase='winner', observed='2026-09-08T00:01:00Z', winning_number=19, status=4)
        self.assertTrue(response.data['duplicate'])
        self.assertEqual(GameRound.objects.count(), 1)
        self.assertEqual(GameRound.objects.get().winner_event_ts.day, 7)

    def test_conflicting_winner_returns_409_without_overwriting(self):
        self.event(phase='winner', winning_number=19, status=3)
        self.assertEqual(self.event(phase='winner', winning_number=14, status=3).status_code, 409)
        self.assertEqual(GameRound.objects.get().winning_number, 19)

    def test_rejects_race_missing_dates_bad_results_and_invalid_rates(self):
        base = {'schema_version': 1, 'game_type': 'lucky28', 'game_no': 'bad',
                'phase': 'winner', 'observed_at': '2026-09-07T23:59:59Z',
                'data': {'winning_number': 19, 'status': 3}}
        for change in [
            {'game_type': 'luckyrace'}, {'observed_at': None}, {'schema_version': 2},
            {'data': {'winning_number': 28, 'status': 3}},
            {'data': {'winning_number': 19, 'status': 2}},
            {'data': {'winning_number': 19, 'status': 3, 'reward_numbers': [1, 2, 3]}},
            {'phase': 'pre', 'data': {'rate_big': 101}},
        ]:
            with self.subTest(change=change):
                response = self.client.post('/api/logger/events/', {**base, **change}, format='json')
                self.assertEqual(response.status_code, 400)
                self.assertEqual(GameRound.objects.count(), 0)

    @patch('games.services.signals.WhatsAppService')
    def test_signal_feedback_is_local_idempotent_and_uses_history_at_event_time(self, whatsapp):
        SignalRule.objects.create(name='Two Big', rule_type='STREAK', dimension='BIG_SMALL',
                                  target_value='Big', threshold=2)
        self.event('earlier', phase='winner', observed='2026-09-07T12:00:00Z', winning_number=14, status=3)
        self.event('future', phase='winner', observed='2026-09-07T12:02:00Z', winning_number=1, status=3)
        response = self.event('current', phase='winner', observed='2026-09-07T12:01:00Z', winning_number=16, status=3)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['signals'][0]['rule__name'], 'Two Big')
        repeated = self.event('current', phase='winner', observed='2026-09-07T12:01:30Z', winning_number=16, status=3)
        self.assertEqual(response.data['signals'], repeated.data['signals'])
        self.assertEqual(SignalLog.objects.count(), 1)
        whatsapp.assert_not_called()

    def test_other_game_type_cannot_be_overwritten(self):
        GameRound.objects.create(game_no='round-1', game_type='luckyrace')
        self.assertEqual(self.event().status_code, 409)
        self.assertEqual(GameRound.objects.get().game_type, 'luckyrace')
