from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import requests
from django.core.exceptions import ValidationError
from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from games.group_config import COLOR_GROUPS, GROUP_BY_NUMBER, MAX_GROUP_THRESHOLD, parse_threshold
from games.models import (GameRound, GroupAbsenceStream, GroupAbsenceState, GroupAbsenceChange,
                          GroupAbsenceEvent, GroupDataIssue, AlertDestination, AlertDelivery)
from games.services.group_absence import synchronize, save_settings, alert_state
from games.services.alert_delivery import deliver_one
from games.services.alert_presentation import format_message


class GroupMappingTests(SimpleTestCase):
    def test_ac01_exact_partition(self):
        self.assertEqual([g.numbers for g in COLOR_GROUPS], [
            (0, 1, 26, 27), (2, 3, 24, 25), (4, 5, 22, 23), (6, 7, 20, 21),
            (8, 9, 18, 19), (10, 11, 16, 17), (12, 13, 14, 15)])
        self.assertEqual(sorted(n for g in COLOR_GROUPS for n in g.numbers), list(range(28)))
        self.assertEqual(len(GROUP_BY_NUMBER), 28)

    def test_strict_thresholds(self):
        for value in ('', '0', '-1', '1.0', '1.5', 'abc', '1e3', str(MAX_GROUP_THRESHOLD + 1), '999999999999999999', True):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                parse_threshold(value, True)
        self.assertEqual(parse_threshold(' 20 ', True), 20)
        self.assertEqual(parse_threshold(str(MAX_GROUP_THRESHOLD), True), MAX_GROUP_THRESHOLD)
        self.assertIsNone(parse_threshold('', False))


@override_settings(ALERT_TELEGRAM_ENABLED=True, ALERT_TELEGRAM_BOT_TOKEN='fake-test-token', LOGGER_API_TOKEN='test')
class GroupAbsenceTests(TestCase):
    def setUp(self):
        self.base = datetime(2026, 10, 19, 23, 59, 0, tzinfo=dt_timezone.utc)
        self.destination = AlertDestination.objects.create(name='Test', chat_id='123', enabled=True, use_cards=True)
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        override = override_settings(ALERT_STATE_DIR=Path(self.directory.name))
        override.enable()
        self.addCleanup(override.disable)
        self.api = APIClient()
        self.api.credentials(HTTP_X_LUCKY28_TOKEN='test')

    def result(self, index, number, stream='lucky28', status=3, evaluate=True):
        game, _ = GameRound.objects.update_or_create(game_no=f'{"R" if stream == "lucky28" else stream}{index}',
            defaults=dict(game_type=stream, has_winner=True, winning_number=number, status=status,
                          winner_event_ts=self.base + timedelta(minutes=index)))
        if evaluate:
            synchronize(stream)
        return game

    def configure(self, thresholds=None, enabled=True, stream='lucky28'):
        thresholds = {'G01': 3} if thresholds is None else thresholds
        values = {g.id: dict(enabled=g.id in thresholds, threshold=thresholds.get(g.id)) for g in COLOR_GROUPS}
        return save_settings(stream, enabled, values, 'tester')

    def state(self, group='G01', stream='lucky28'):
        return GroupAbsenceState.objects.get(stream_id=stream, group_id=group)

    def event(self, round_id, number, status=3):
        return self.api.post('/api/logger/events/', dict(schema_version=1, game_type='lucky28', game_no=round_id,
            phase='winner', observed_at=timezone.now().isoformat(), data=dict(winning_number=number, status=status)), format='json')

    def test_initial_disabled_and_ac02_members_reset_zero(self):
        stream, states = synchronize()
        self.assertFalse(stream.enabled)
        self.assertTrue(all(not s.enabled and s.threshold is None for s in states))
        for i, number in enumerate(range(28)):
            before = {s.group_id: s.absence for s in GroupAbsenceState.objects.all()}
            self.result(i, number)
            for state in GroupAbsenceState.objects.all():
                self.assertEqual(state.absence, 0 if state.group_id == GROUP_BY_NUMBER[number].id else before[state.group_id] + 1)
        self.assertEqual(GroupAbsenceEvent.objects.count(), 0)

    def test_ac03_to_ac05_boundary_repeat_reset_and_new_absence(self):
        self.configure({'G01': 20})
        self.result(0, 26)
        for i in range(1, 20):
            self.result(i, 8)
        self.assertEqual(self.state().absence, 19)
        self.assertEqual(GroupAbsenceEvent.objects.count(), 0)
        self.result(20, 8)
        self.assertEqual(GroupAbsenceEvent.objects.count(), 1)
        self.result(21, 12)
        self.result(22, 6)
        self.assertEqual(self.state().absence, 22)
        self.assertEqual(GroupAbsenceEvent.objects.count(), 1)
        self.result(23, 1)
        self.assertEqual(self.state().absence, 0)
        self.assertIsNotNone(GroupAbsenceEvent.objects.get().resolved_at)
        for i in range(24, 44):
            self.result(i, 8)
        self.assertEqual(GroupAbsenceEvent.objects.count(), 2)
        self.assertEqual(AlertDelivery.objects.filter(kind='group').count(), 2)

    def test_ac06_ac10_independent_thresholds_and_simultaneous_events(self):
        self.configure({g.id: i + 1 for i, g in enumerate(COLOR_GROUPS)})
        for i in range(7):
            self.result(i, 14)
        self.assertEqual(GroupAbsenceEvent.objects.count(), 6)
        self.assertEqual({e.group_id: e.snapshot['absence'] for e in GroupAbsenceEvent.objects.all()},
                         {g.id: i + 1 for i, g in enumerate(COLOR_GROUPS[:-1])})
        GroupAbsenceEvent.objects.all().delete()
        # A separate stream starts six qualifying groups together, with its own counters.
        for i in range(4):
            self.result(i, 14, stream='other')
        self.configure({g.id: 3 for g in COLOR_GROUPS}, stream='other')
        self.assertEqual(GroupAbsenceEvent.objects.filter(stream_id='other').count(), 6)
        self.assertEqual(self.state(stream='other').absence, 4)
        self.assertEqual(self.state().absence, 7)

    def test_ac07_ac08_lower_raise_disable_and_same_save(self):
        self.configure({'G01': 20})
        for i, number in enumerate([26, 8, 12, 6]):
            self.result(i, number)
        self.configure({'G01': 2})
        self.assertEqual(GroupAbsenceEvent.objects.count(), 1)
        self.configure({'G01': 30})
        stream, states = synchronize()
        self.assertEqual(alert_state(stream, states[0]), 'Below threshold')
        self.configure({'G01': 1}, enabled=False)
        self.configure({'G01': 1}, enabled=True)
        changes = GroupAbsenceChange.objects.count()
        self.configure({'G01': 1}, enabled=True)
        self.assertEqual(GroupAbsenceChange.objects.count(), changes)
        self.assertEqual(self.state().absence, 3)
        self.assertEqual(GroupAbsenceEvent.objects.count(), 1)
        self.assertEqual(AlertDelivery.objects.count(), 1)
        self.assertEqual(GroupAbsenceChange.objects.last().editor, 'tester')

    def test_enable_after_tracking_while_paused(self):
        self.configure({'G01': 2}, enabled=False)
        for i in range(3):
            self.result(i, 8)
        self.assertEqual(GroupAbsenceEvent.objects.count(), 0)
        self.configure({'G01': 2})
        self.assertEqual(GroupAbsenceEvent.objects.count(), 1)

    def test_ac09_invalid_save_atomic_and_ui_errors(self):
        self.configure({'G01': 20})
        before = GroupAbsenceChange.objects.count()
        for invalid in ('', '0', '-1', '1.2', 'x', '1000001'):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                self.configure({'G01': 1, 'G07': invalid}, enabled=False)
            self.assertEqual(self.state().threshold, 20)
            self.assertTrue(GroupAbsenceStream.objects.get().enabled)
        self.assertEqual(GroupAbsenceChange.objects.count(), before)
        response = self.client.post('/alerts/groups/settings/', {'enabled': 'on', 'G01_enabled': 'on', 'G01_threshold': '1.0'},
                                    REMOTE_ADDR='127.0.0.1', HTTP_HOST='localhost')
        self.assertContains(response, 'Enter a whole number of rounds greater than 0.', status_code=400)
        self.assertEqual(self.state().threshold, 20)

    def test_ac11_duplicates_restart_and_api_integration(self):
        self.configure({'G01': 1})
        self.assertEqual(self.event('R100', 26).status_code, 200)
        self.assertEqual(self.event('R101', 8).status_code, 200)
        self.assertTrue(self.event('R101', 8).json()['duplicate'])
        synchronize(force=True)
        synchronize(force=True)
        self.assertEqual(self.state().absence, 1)
        self.assertEqual(GroupAbsenceEvent.objects.count(), 1)
        self.assertEqual(AlertDelivery.objects.count(), 1)
        self.assertEqual(self.event('R101', 6).status_code, 409)
        self.assertEqual(self.state().absence, 1)

    def test_ac12_missing_ids_reordered_results_and_correction(self):
        self.configure({'G01': 2})
        self.result(100, 26)
        self.result(103, 8)
        self.result(104, 12)
        stream, states = synchronize()
        self.assertFalse(stream.complete)
        self.assertEqual(states[0].absence, 2)  # Not external ID subtraction.
        self.assertEqual(GroupAbsenceEvent.objects.count(), 0)
        self.result(102, 6)
        self.assertEqual(GroupAbsenceEvent.objects.count(), 0)
        self.result(101, 10)
        self.assertTrue(GroupAbsenceStream.objects.get().complete)
        self.assertEqual(self.state().absence, 4)
        self.assertEqual(GroupAbsenceEvent.objects.count(), 1)
        # Insert a last appearance inside the already-notified current period.
        self.result(102, 1)
        self.assertEqual(self.state().absence, 2)
        self.assertTrue(self.state().notified)
        self.assertEqual(GroupAbsenceEvent.objects.count(), 1)
        self.result(104, 26)
        self.assertFalse(self.state().notified)
        self.assertIsNotNone(GroupAbsenceEvent.objects.get().resolved_at)
        self.result(105, 8)
        self.result(106, 8)
        self.assertEqual(GroupAbsenceEvent.objects.count(), 2)

    def test_invalid_pending_cancelled_rounds_and_reconciliation(self):
        self.configure({'G01': 1})
        self.assertEqual(self.event('R100', 26).status_code, 200)
        self.assertEqual(self.event('R101', 28).status_code, 400)
        self.assertEqual(GroupDataIssue.objects.count(), 1)
        self.assertEqual(self.event('R102', 8).status_code, 200)
        self.assertEqual(GroupAbsenceEvent.objects.count(), 0)
        self.assertEqual(self.event('R101', 8, status=2).status_code, 400)
        self.assertEqual(self.event('R101', 8).status_code, 200)
        self.assertEqual(GroupDataIssue.objects.count(), 0)
        self.assertEqual(GroupAbsenceEvent.objects.count(), 1)
        GameRound.objects.create(game_no='R103', game_type='lucky28', has_pre=True, pre_event_ts=timezone.now())
        self.assertTrue(synchronize()[0].complete)  # Open next round is not missing yet.
        self.result(104, 6)
        self.assertFalse(synchronize()[0].complete)
        self.result(103, 12, status=0)
        self.assertFalse(synchronize()[0].complete)
        self.result(103, 12)
        self.assertTrue(synchronize()[0].complete)

    def test_ac13_unseen_lower_bound_and_full_notification_content(self):
        self.configure({'G01': 2})
        self.result(100, 8)
        self.result(101, 6)
        event = GroupAbsenceEvent.objects.get()
        self.assertTrue(event.snapshot['lower_bound'])
        self.assertIsNone(event.snapshot['last_number'])
        text = format_message(event.snapshot, 'group')
        for expected in ('G01', 'Red', '[0, 1, 26, 27]', 'at least 2', 'Threshold: 2',
                         'Not seen in available history', 'R101', 'Alert time:', '/games/detail/R101/'):
            self.assertIn(expected, text)

    @override_settings(TIME_ZONE='Asia/Kolkata', ALERT_PUBLIC_BASE_URL='https://example.com')
    def test_ac14_midnight_timezone_and_daily_threshold(self):
        self.configure({'G01': 20})
        self.result(0, 26)
        self.result(1, 8)
        self.result(2, 12)
        self.configure({'G01': 2})
        event = GroupAbsenceEvent.objects.get()
        self.assertEqual(self.state().absence, 2)
        self.assertIn('+05:30', event.snapshot['last_timestamp'])
        self.assertEqual(event.snapshot['details_url'], 'https://example.com/games/detail/R2/')
        self.assertIn('href="https://example.com/', format_message(event.snapshot, 'group'))

    def test_restore_evaluates_only_latest_not_old_threshold_crossings(self):
        self.configure({'G01': 2})
        for i, number in enumerate([26, 8, 8, 8, 1, 8]):
            self.result(i, number, evaluate=False)
        synchronize(force=True)
        self.assertEqual(self.state().absence, 1)
        self.assertEqual(GroupAbsenceEvent.objects.count(), 0)
        self.result(6, 8)
        synchronize(force=True)
        self.assertEqual(GroupAbsenceEvent.objects.count(), 1)

    @patch('games.services.alert_delivery.requests.post')
    def test_ac15_delivery_retries_same_event_and_ambiguous_no_retry(self, post):
        self.configure({'G01': 1})
        self.result(0, 8)
        delivery = AlertDelivery.objects.get()
        original_key = delivery.dedup_key
        post.return_value = Mock(status_code=429, json=Mock(return_value={'ok': False, 'parameters': {'retry_after': 1}}))
        self.assertTrue(deliver_one(delivery.pk))
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'pending')
        AlertDelivery.objects.filter(pk=delivery.pk).update(available_at=timezone.now())
        post.return_value = Mock(status_code=200, json=Mock(return_value={'ok': True, 'result': {'message_id': 42}}))
        self.assertTrue(deliver_one(delivery.pk))
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'sent')
        self.assertEqual(delivery.dedup_key, original_key)
        self.assertEqual(delivery.attempts, 2)
        self.assertFalse(deliver_one(delivery.pk))
        self.result(1, 26)
        self.result(2, 8)
        delivery = AlertDelivery.objects.latest('pk')
        post.side_effect = requests.Timeout()
        self.assertTrue(deliver_one(delivery.pk))
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'uncertain')
        self.assertFalse(deliver_one(delivery.pk))
        synchronize(force=True)
        self.assertEqual(AlertDelivery.objects.count(), 2)

    @patch('games.services.alert_delivery.requests.post')
    def test_dispatch_pauses_for_gaps_disable_and_raised_threshold(self, post):
        self.configure({'G01': 1})
        self.result(0, 8)
        delivery = AlertDelivery.objects.get()
        self.result(2, 8)
        self.assertTrue(deliver_one(delivery.pk))
        self.assertFalse(post.called)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'pending')
        self.result(1, 8)
        self.configure({'G01': 100})
        AlertDelivery.objects.filter(pk=delivery.pk).update(available_at=timezone.now())
        self.assertTrue(deliver_one(delivery.pk))
        self.assertFalse(post.called)
        self.result(3, 26)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'cancelled')

    def test_management_access_templates_and_successful_save(self):
        self.result(0, 8)
        self.assertEqual(self.client.get('/alerts/groups/').status_code, 403)
        local = dict(REMOTE_ADDR='127.0.0.1', HTTP_HOST='localhost')
        response = self.client.get('/alerts/groups/', **local)
        self.assertContains(response, 'Group Absence Alerts')
        self.assertContains(response, 'Not seen in available history')
        self.assertContains(response, 'Orange')
        self.assertContains(response, 'Magenta')
        response = self.client.get('/alerts/groups/settings/', **local)
        self.assertContains(response, 'Cancel')
        response = self.client.post('/alerts/groups/settings/', {'enabled': 'on', 'G01_enabled': 'on', 'G01_threshold': ' 1 '}, follow=True, **local)
        self.assertContains(response, 'saved and applied immediately')
        self.assertEqual(GroupAbsenceEvent.objects.count(), 1)
        self.assertEqual(GroupAbsenceChange.objects.last().editor, 'Local operator')
        self.assertContains(self.client.get('/alerts/groups/', **local), 'Active absence')

    def test_deleted_history_marks_dirty_and_retains_event_history(self):
        self.configure({'G01': 1})
        self.result(0, 26)
        game = self.result(1, 8)
        game.delete()
        stream, states = synchronize()
        self.assertEqual(states[0].absence, 0)
        self.assertEqual(GroupAbsenceEvent.objects.count(), 1)
        self.assertIsNotNone(GroupAbsenceEvent.objects.get().resolved_at)

    def test_outbox_and_state_rollback_together(self):
        self.configure({'G01': 1})
        self.result(0, 26)
        self.result(1, 8, evaluate=False)
        with patch('games.services.group_absence.queue_delivery', side_effect=RuntimeError('simulated database failure')):
            with self.assertRaises(RuntimeError):
                synchronize()
        self.assertEqual(GroupAbsenceEvent.objects.count(), 0)
        self.assertFalse(self.state().notified)
        self.assertEqual(self.state().absence, 0)
        self.assertTrue(GroupAbsenceStream.objects.get().dirty)
        synchronize()
        self.assertEqual(GroupAbsenceEvent.objects.count(), 1)
        self.assertEqual(AlertDelivery.objects.count(), 1)

    def test_malformed_envelope_is_rejected_without_500(self):
        self.assertEqual(self.api.post('/api/logger/events/', [], format='json').status_code, 400)
        self.assertEqual(GroupDataIssue.objects.count(), 0)

    @patch('games.services.alert_delivery.requests.post')
    def test_corrected_pending_message_uses_current_evidence_same_key(self, post):
        self.configure({'G01': 2})
        for i, number in enumerate([26, 8, 8, 8, 8]):
            self.result(i, number)
        delivery = AlertDelivery.objects.get()
        key = delivery.dedup_key
        self.result(1, 1)
        self.assertEqual(GroupAbsenceEvent.objects.count(), 1)
        post.return_value = Mock(status_code=200, json=Mock(return_value={'ok': True, 'result': {'message_id': 42}}))
        deliver_one(delivery.pk)
        delivery.refresh_from_db()
        self.assertEqual(delivery.dedup_key, key)
        self.assertEqual(delivery.payload['last_round'], 'R1')
        self.assertEqual(delivery.payload['absence'], 3)
        self.assertTrue(post.call_args.args[0].endswith('/sendPhoto'))
        self.assertIn('Last appearance: 1 in round R1', post.call_args.kwargs['data']['caption'])
