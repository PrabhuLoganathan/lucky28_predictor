import json
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import pandas as pd
import requests
from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from games.models import (GameRound, WindowAlertState, WindowAlertEvent, AlertDestination, AlertDelivery)
from games.services.window_alerts import synchronize, save_settings, current_window
from games.services.group_absence import report_issue
from games.services.repetition import summarize_window
from games.services.analysis import AnalysisService
from games.services.alert_delivery import deliver_one
from games.services.alert_presentation import format_message


class WindowFactsTests(SimpleTestCase):
    def test_examples_and_shared_analysis_table(self):
        unique = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18]
        repeat = unique[1:] + [8]
        self.assertFalse(summarize_window(unique)['has_repetition'])
        self.assertTrue(summarize_window(repeat)['newest_repeats'])
        self.assertEqual(summarize_window(repeat)['repeated_details'], '8x2')
        df = pd.DataFrame(dict(winning_number=unique + [8], game_no=range(11)))
        rows = AnalysisService(df).get_repetition_analysis()
        self.assertEqual(rows[0]['numbers'], repeat)
        self.assertEqual(rows[0]['repeated_details'], '8x2')
        self.assertFalse(rows[1]['has_repetition'])

    def test_old_repeat_pair_does_not_make_newest_a_repeat(self):
        sample = [8, 8, 1, 2, 3, 4, 5, 6, 7, 9]
        result = summarize_window(sample)
        self.assertTrue(result['has_repetition'])
        self.assertFalse(result['newest_repeats'])


@override_settings(ALERT_TELEGRAM_ENABLED=True, ALERT_TELEGRAM_BOT_TOKEN='fake-test-token', LOGGER_API_TOKEN='test')
class WindowAlertTests(TestCase):
    def setUp(self):
        self.base = timezone.now() - timedelta(minutes=60)
        self.destination = AlertDestination.objects.create(name='Test', chat_id='123', enabled=True, use_cards=True)
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        override = override_settings(ALERT_STATE_DIR=Path(self.directory.name))
        override.enable()
        self.addCleanup(override.disable)

    def result(self, index, number, evaluate=True, stream='lucky28', **extra):
        values = dict(game_type=stream, has_winner=True, winning_number=number, status=3,
                      winner_event_ts=self.base + timedelta(seconds=index))
        values.update(extra)
        game, _ = GameRound.objects.update_or_create(game_no=f'{"R" if stream == "lucky28" else stream}{index}', defaults=values)
        if evaluate:
            synchronize(stream)
        return game

    def sequence(self, numbers, start=100, **kwargs):
        for index, number in enumerate(numbers, start):
            self.result(index, number, **kwargs)

    def enable(self, drought=True, repeat=True):
        return save_settings('lucky28', drought, repeat)

    def test_disabled_initially_and_nine_results_do_not_alert(self):
        state = synchronize()
        self.assertFalse(state.drought_enabled)
        self.assertFalse(state.repeat_enabled)
        self.enable()
        self.sequence(range(9))
        self.assertEqual(current_window('lucky28')['status'], 'Waiting for 10 results')
        self.assertEqual(WindowAlertEvent.objects.count(), 0)
        self.result(109, 9)
        event = WindowAlertEvent.objects.get()
        self.assertEqual(event.kind, 'drought')
        self.assertEqual(event.snapshot['numbers'], list(range(10)))
        self.assertEqual(event.snapshot['start_round'], 'R100')
        self.assertEqual(event.snapshot['end_round'], 'R109')

    def test_drought_once_rearms_after_repeat_and_continues_across_midnight(self):
        self.base = timezone.now().replace(hour=23, minute=58, second=10, microsecond=0)
        self.enable()
        self.sequence(range(10))
        self.result(110, 10)
        self.result(111, 11)
        self.assertEqual(WindowAlertEvent.objects.filter(kind='drought').count(), 1)
        self.result(112, 11)
        self.assertEqual(WindowAlertEvent.objects.filter(kind='repeat').count(), 1)
        self.sequence(range(12, 21), start=113)
        self.assertEqual(current_window('lucky28')['status'], 'Drought')
        self.assertEqual(WindowAlertEvent.objects.filter(kind='drought').count(), 2)
        self.assertEqual(WindowAlertEvent.objects.filter(kind='repeat').count(), 1)

    def test_newest_repeat_boundary_nine_prior_results_and_old_pair(self):
        self.enable(drought=False)
        self.sequence([8, 0, 1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(WindowAlertEvent.objects.count(), 1)
        self.result(110, 8)
        self.assertEqual(WindowAlertEvent.objects.count(), 2)
        self.result(111, 9)  # Old 8 pair remains, but 9 does not repeat.
        self.assertEqual(current_window('lucky28')['status'], 'Repeat')
        self.assertEqual(WindowAlertEvent.objects.count(), 2)
        self.result(112, 2)  # Previous 2 at R103 is the first slot of the new window.
        self.assertEqual(WindowAlertEvent.objects.count(), 3)
        self.result(113, 2)
        self.assertEqual(WindowAlertEvent.objects.count(), 4)

    def test_repeat_ten_rounds_ago_is_outside_window(self):
        self.enable(drought=False)
        self.sequence(range(10))
        self.result(110, 0)
        self.assertEqual(WindowAlertEvent.objects.count(), 0)
        self.assertEqual(current_window('lucky28')['status'], 'Drought')

    def test_restart_duplicate_refresh_and_enable_toggles_are_deduplicated(self):
        self.enable()
        self.sequence(range(10))
        for _ in range(3):
            synchronize()
            self.enable(False, False)
            self.enable()
            self.result(109, 9)
        self.assertEqual(WindowAlertEvent.objects.count(), 1)
        self.assertEqual(AlertDelivery.objects.filter(kind='window').count(), 1)
        self.assertTrue(WindowAlertState.objects.get().drought_enabled)

    def test_missing_round_does_not_get_skipped_and_late_fill_reconciles(self):
        self.enable()
        self.sequence(range(5))
        self.sequence(range(6, 11), start=106)
        self.assertEqual(current_window('lucky28')['status'], 'Data incomplete')
        self.assertEqual(WindowAlertEvent.objects.count(), 0)
        self.result(105, 5)
        self.assertEqual(WindowAlertEvent.objects.count(), 1)
        self.assertEqual(WindowAlertEvent.objects.get().snapshot['numbers'], list(range(1, 11)))

    def test_old_gaps_do_not_block_a_new_complete_window(self):
        self.enable()
        self.result(1, 3)
        self.result(2, 28)
        report_issue('lucky28', 'R3', 'Invalid historical result')
        self.sequence(range(10), start=100)
        self.assertEqual(current_window('lucky28')['status'], 'Drought')
        self.assertEqual(WindowAlertEvent.objects.count(), 1)

    def test_invalid_cancelled_pending_and_missing_timestamp(self):
        self.enable()
        self.sequence(range(9))
        self.result(109, 9, status=2)
        self.assertEqual(current_window('lucky28')['status'], 'Data incomplete')
        self.assertEqual(WindowAlertEvent.objects.count(), 0)
        self.result(109, 9)
        GameRound.objects.create(game_no='R110', game_type='lucky28', has_pre=True, pre_event_ts=timezone.now())
        self.assertEqual(current_window('lucky28')['status'], 'Drought')
        self.result(110, 10, winner_event_ts=None)
        self.assertEqual(current_window('lucky28')['status'], 'Data incomplete')
        self.result(110, 10)
        report_issue('lucky28', 'R111', 'Invalid latest result')
        self.assertEqual(current_window('lucky28')['status'], 'Data incomplete')
        self.result(111, 11)
        self.assertEqual(current_window('lucky28')['status'], 'Drought')

    def test_startup_does_not_replay_old_windows(self):
        self.enable()
        self.sequence(list(range(10)) + [9, 10, 11], evaluate=False)
        synchronize()
        self.assertEqual(WindowAlertEvent.objects.count(), 0)  # Old repeat persists, newest 11 is new.
        self.result(113, 11)
        self.assertEqual(WindowAlertEvent.objects.count(), 1)

    def test_separate_streams(self):
        self.enable()
        self.sequence(range(10))
        self.sequence([1] * 10, stream='other')
        self.assertEqual(WindowAlertEvent.objects.count(), 1)
        self.assertEqual(current_window('other')['status'], 'Repeat')
        self.assertEqual(current_window('lucky28')['status'], 'Drought')

    def test_corrected_window_cancels_unsent_event_without_replay(self):
        self.enable()
        self.sequence(range(10))
        event = WindowAlertEvent.objects.get()
        delivery = AlertDelivery.objects.get(kind='window')
        self.result(101, 0)  # Earlier pair; latest number is not itself repeating.
        event.refresh_from_db()
        delivery.refresh_from_db()
        self.assertIsNotNone(event.invalidated_at)
        self.assertEqual(delivery.status, 'cancelled')
        self.assertEqual(WindowAlertEvent.objects.count(), 1)
        synchronize()
        self.assertEqual(WindowAlertEvent.objects.count(), 1)

    def test_state_and_outbox_rollback_together(self):
        self.enable()
        self.sequence(range(10), evaluate=False)
        with patch('games.services.window_alerts.queue_delivery', side_effect=RuntimeError('simulated failure')):
            with self.assertRaises(RuntimeError):
                synchronize()
        self.assertEqual(WindowAlertEvent.objects.count(), 0)
        synchronize()
        self.assertEqual(WindowAlertEvent.objects.count(), 1)

    @patch('games.services.alert_delivery.requests.post')
    def test_delivery_content_retry_key_and_ambiguous_delivery(self, post):
        self.enable()
        self.sequence(range(10))
        delivery = AlertDelivery.objects.get(kind='window')
        key = delivery.dedup_key
        post.return_value = Mock(status_code=429, json=Mock(return_value={'ok': False, 'parameters': {'retry_after': 1}}))
        deliver_one(delivery.pk)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'pending')
        AlertDelivery.objects.filter(pk=delivery.pk).update(available_at=timezone.now())
        post.return_value = Mock(status_code=200, json=Mock(return_value={'ok': True, 'result': [{'message_id': i, 'media_group_id': 'album-test'} for i in (42, 43, 44)]}))
        deliver_one(delivery.pk)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'sent')
        self.assertEqual(delivery.dedup_key, key)
        self.assertEqual(post.call_args.args[0].split('/')[-1], 'sendMediaGroup')
        self.assertIn('All 10 completed results are different', json.loads(post.call_args.kwargs['data']['media'])[0]['caption'])
        self.result(110, 9)
        delivery = AlertDelivery.objects.latest('pk')
        text = format_message(delivery.payload, 'window')
        self.assertIn('Newest result 9 appears 2 times', text)
        post.side_effect = requests.Timeout()
        deliver_one(delivery.pk)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'uncertain')
        self.assertFalse(deliver_one(delivery.pk))

    @patch('games.services.alert_delivery.requests.post')
    def test_disabled_or_expired_delivery_is_not_sent(self, post):
        self.enable()
        self.sequence(range(10))
        delivery = AlertDelivery.objects.get(kind='window')
        self.enable(False, False)
        deliver_one(delivery.pk)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'pending')
        self.enable()
        WindowAlertEvent.objects.update(created_at=timezone.now() - timedelta(seconds=121))
        AlertDelivery.objects.filter(pk=delivery.pk).update(available_at=timezone.now())
        deliver_one(delivery.pk)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'cancelled')
        self.assertFalse(post.called)

    def test_logger_integration_and_duplicate_winner(self):
        self.enable()
        self.sequence(range(9))
        api = APIClient()
        api.credentials(HTTP_X_LUCKY28_TOKEN='test')
        data = dict(schema_version=1, game_type='lucky28', game_no='R109', phase='winner',
                    observed_at=timezone.now().isoformat(), data=dict(winning_number=9, status=3))
        self.assertEqual(api.post('/api/logger/events/', data, format='json').status_code, 200)
        self.assertTrue(api.post('/api/logger/events/', data, format='json').json()['duplicate'])
        self.assertEqual(WindowAlertEvent.objects.count(), 1)

    def test_management_access_save_and_settings_persistence(self):
        self.sequence(range(10))
        self.assertEqual(self.client.get('/alerts/windows/').status_code, 403)
        local = dict(REMOTE_ADDR='127.0.0.1', HTTP_HOST='localhost')
        self.assertContains(self.client.get('/alerts/windows/', **local), 'All 10 results are different')
        response = self.client.post('/alerts/windows/', dict(drought_enabled='on', repeat_enabled='on'), follow=True, **local)
        self.assertContains(response, '10-game alert settings saved and applied immediately.')
        self.assertEqual(WindowAlertEvent.objects.count(), 1)
        self.assertContains(response, 'None — all different')
        self.assertTrue(WindowAlertState.objects.get().repeat_enabled)
