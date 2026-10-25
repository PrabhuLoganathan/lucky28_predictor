from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from games.group_config import COLOR_GROUPS
from games.models import (GameRound, GroupAbsenceEnding, GroupAbsenceState,
                          GroupAbsenceChange, AlertDelivery, AlertDestination)
from games.services.group_absence import synchronize, save_settings, eligible
from games.services.group_endings import delivery_gate
from games.services.alert_presentation import format_message
from games.services.alert_card import card_model
from games.services.alert_delivery import deliver_one


class GroupEndingTests(TestCase):
    def setUp(self):
        self.base = timezone.now() - timedelta(seconds=60)
        self.destination = AlertDestination.objects.create(name='Test only', chat_id='123', enabled=True)
        self.local = dict(REMOTE_ADDR='127.0.0.1', HTTP_HOST='localhost')

    def result(self, index, number, evaluate=True, stream='lucky28'):
        game, _ = GameRound.objects.update_or_create(game_no=f'{stream}R{index}', defaults=dict(
            game_type=stream, has_winner=True, winning_number=number, status=3,
            winner_event_ts=self.base + timedelta(seconds=index)))
        if evaluate:
            synchronize(stream)
        return game

    def configure(self, threshold=3, enabled=True, stream='lucky28', start_threshold=None):
        values = {g.id: dict(enabled=g.id == 'G01' and start_threshold is not None,
            threshold=start_threshold if g.id == 'G01' else None,
            ending_enabled=g.id == 'G01' and enabled,
            ending_threshold=threshold if g.id == 'G01' else None) for g in COLOR_GROUPS}
        return save_settings(stream, True, values, 'test')

    def ending(self):
        return GroupAbsenceEnding.objects.get()

    def test_exact_threshold_independent_of_start_alert_and_no_duplicates(self):
        self.configure()
        for i, n in enumerate([0, 8, 12, 6, 27]):
            self.result(i, n)
        event = self.ending()
        self.assertEqual(event.snapshot['count'], 3)
        self.assertEqual(event.snapshot['ended_number'], 27)
        self.assertEqual(event.snapshot['last_round'], 'lucky28R0')
        self.assertEqual(AlertDelivery.objects.get().kind, 'group_end')
        self.assertEqual(delivery_gate(AlertDelivery.objects.get().payload), 'ready')
        synchronize(force=True)
        self.result(4, 27)
        self.configure(threshold=1)
        self.assertEqual(GroupAbsenceEnding.objects.count(), 1)
        self.assertEqual(AlertDelivery.objects.count(), 1)
        for i, n in enumerate([8, 0], 5):
            self.result(i, n)
        self.assertEqual(GroupAbsenceEnding.objects.count(), 2)

    def test_below_threshold_and_immediate_repeat_do_not_end_a_qualifying_gap(self):
        self.configure()
        for i, n in enumerate([0, 8, 6, 1, 26]):
            self.result(i, n)
        self.assertFalse(GroupAbsenceEnding.objects.exists())

    def test_group_return_ends_absence_not_departure_after_a_hit_streak(self):
        self.configure(threshold=2)
        # Red has three hits, then two misses. Its hit streak breaking must not
        # produce a Red absence-ended event; only the returning Red result does.
        for i, n in enumerate([0, 1, 26, 8, 12]):
            self.result(i, n)
            self.assertFalse(GroupAbsenceEnding.objects.exists())
        self.result(5, 27)
        event = self.ending()
        self.assertEqual(event.snapshot['mode'], 'absence')
        self.assertEqual(event.snapshot['count'], 2)
        self.assertEqual(event.snapshot['ended_number'], 27)

    def test_missing_round_blocks_ending_but_old_gap_does_not_block_later_period(self):
        self.configure(threshold=2, start_threshold=2)
        for i, n in [(0, 0), (2, 8), (3, 8), (4, 1)]:
            self.result(i, n)
        self.assertFalse(GroupAbsenceEnding.objects.exists())
        self.result(5, 8)
        self.result(6, 8)
        stream, states = synchronize()
        self.assertFalse(stream.complete)  # Historical gap still reported.
        red = next(s for s in states if s.group_id == 'G01')
        self.assertTrue(red.complete)
        self.assertTrue(eligible(stream, red))
        self.result(7, 26)
        self.assertEqual(self.ending().snapshot['count'], 2)

    def test_no_ending_from_unknown_previous_appearance(self):
        self.configure(threshold=2)
        for i, n in enumerate([8, 8, 8, 0]):
            self.result(i, n)
        self.assertFalse(GroupAbsenceEnding.objects.exists())

    def test_enabling_after_ending_and_initial_import_do_not_replay(self):
        for i, n in enumerate([0, 8, 8, 8, 1]):
            self.result(i, n, evaluate=False)
        self.configure()
        synchronize(force=True)
        self.assertFalse(GroupAbsenceEnding.objects.exists())
        self.configure(enabled=False)
        for i, n in enumerate([8, 8, 8, 0], 5):
            self.result(i, n)
        self.configure()
        self.assertFalse(GroupAbsenceEnding.objects.exists())

    def test_batch_after_existing_cursor_captures_one_ending(self):
        self.configure(threshold=2)
        self.result(0, 0)
        for i, n in enumerate([8, 8, 1, 8], 1):
            self.result(i, n, evaluate=False)
        synchronize()
        self.assertEqual(self.ending().ending_round, 'lucky28R3')

    def test_correction_cancels_unsent_ending_preserving_original_evidence(self):
        self.configure(threshold=2)
        for i, n in enumerate([0, 8, 8, 1]):
            self.result(i, n)
        original = self.ending().snapshot
        self.result(2, 26)
        self.assertTrue(self.ending().invalidated)
        self.assertEqual(self.ending().snapshot, original)
        self.assertEqual(AlertDelivery.objects.get().status, 'cancelled')
        self.assertEqual(delivery_gate(AlertDelivery.objects.get().payload), 'cancelled')

    def test_raised_threshold_and_disabled_ending_pause_pending_delivery(self):
        self.configure(threshold=2)
        for i, n in enumerate([0, 8, 8, 1]):
            self.result(i, n)
        payload = AlertDelivery.objects.get().payload
        self.configure(threshold=3)
        self.assertEqual(delivery_gate(payload), 'pending')
        self.configure(threshold=2, enabled=False)
        self.assertEqual(delivery_gate(payload), 'pending')

    def test_old_replayed_result_does_not_notify(self):
        self.base -= timedelta(days=1)
        self.configure(threshold=2)
        for i, n in enumerate([0, 8, 8, 1]):
            self.result(i, n)
        self.assertFalse(GroupAbsenceEnding.objects.exists())

    def test_validation_audit_and_settings_page(self):
        self.configure(threshold=3)
        before = GroupAbsenceChange.objects.count()
        for invalid in [0, -1, '1.2', '', 1000001]:
            with self.subTest(value=invalid), self.assertRaises(ValidationError):
                self.configure(threshold=invalid)
        self.assertEqual(GroupAbsenceChange.objects.count(), before)
        self.assertEqual(GroupAbsenceState.objects.get(group_id='G01').ending_threshold, 3)
        page = self.client.get('/alerts/groups/settings/', **self.local)
        self.assertContains(page, 'Minimum missed rounds before return')
        self.assertContains(page, 'G01_ending_threshold')
        post = {'enabled': 'on', 'G01_ending_enabled': 'on', 'G01_ending_threshold': '7'}
        self.assertEqual(self.client.post('/alerts/groups/settings/', post, **self.local).status_code, 302)
        self.assertEqual(GroupAbsenceState.objects.get(group_id='G01').ending_threshold, 7)
        self.assertEqual(GroupAbsenceChange.objects.last().new_value['ending_threshold'], 7)

    def test_card_and_dashboard_show_ending_and_saved_threshold(self):
        self.configure(threshold=2)
        for i, n in enumerate([0, 8, 8, 1]):
            self.result(i, n)
        snapshot = self.ending().snapshot
        text = format_message(snapshot, 'group_end')
        self.assertIn('COLOR ABSENCE ENDED', text)
        self.assertIn('Minimum missed rounds before return: 2', text)
        self.assertIn('Result 1', text)
        model = card_model(snapshot, 'group_end')
        self.assertEqual(model['key'], 'ended')
        self.assertEqual(model['count'], '2')
        self.assertEqual(model['label'], 'COLOR ABSENCE ENDED')
        self.assertEqual(model['metric'], 'missed rounds before return')
        self.assertIn('Returned: 1', model['return_detail'])
        page = self.client.get('/alerts/groups/', **self.local)
        self.assertContains(page, 'Absence ended history')
        self.assertContains(page, 'Returned as 1')

    def test_outbox_failure_rolls_back_ending_and_cursor(self):
        self.configure(threshold=2)
        for i, n in enumerate([0, 8, 8]):
            self.result(i, n)
        self.result(3, 1, evaluate=False)
        with patch('games.services.group_endings.queue_delivery', side_effect=RuntimeError('outbox failure')):
            with self.assertRaises(RuntimeError):
                synchronize()
        self.assertFalse(GroupAbsenceEnding.objects.exists())
        synchronize()
        self.assertEqual(GroupAbsenceEnding.objects.count(), 1)

    def test_stream_isolation(self):
        self.configure(threshold=2)
        for i, n in enumerate([0, 8, 8, 1]):
            self.result(i, n, stream='other')
        self.assertFalse(GroupAbsenceEnding.objects.exists())

    @override_settings(ALERT_TELEGRAM_ENABLED=True, ALERT_TELEGRAM_BOT_TOKEN='fake-test-token')
    @patch('games.services.alert_delivery.requests.post')
    def test_delivery_formats_ending_and_never_sends_twice(self, post):
        self.configure(threshold=2)
        for i, n in enumerate([0, 8, 8, 1]):
            self.result(i, n)
        delivery = AlertDelivery.objects.get()
        post.return_value = Mock(status_code=200,
            json=Mock(return_value={'ok': True, 'result': {'message_id': 123}}))
        with TemporaryDirectory() as directory, override_settings(ALERT_STATE_DIR=Path(directory)):
            self.assertTrue(deliver_one(delivery.pk))
            self.assertFalse(deliver_one(delivery.pk))
        self.assertEqual(post.call_count, 1)
        data = post.call_args.kwargs['data']
        self.assertIn('COLOR ABSENCE ENDED', data.get('text', data.get('caption', '')))
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'sent')
