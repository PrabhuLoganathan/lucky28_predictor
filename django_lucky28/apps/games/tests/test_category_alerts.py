from datetime import timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import requests
from PIL import Image
from django.core.exceptions import ValidationError
from django.test import TestCase, SimpleTestCase, Client, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from games.category_config import CATEGORIES, CATEGORY_FAMILIES, CATEGORIES_BY_NUMBER, CATEGORY_MODES
from games.models import (GameRound, CategoryAlertSettings, CategoryAlertRule, CategoryAlertEvent,
                          CategoryAlertChange, AlertDestination, AlertDelivery)
from games.services.category_alerts import synchronize, save_settings
from games.services.alert_delivery import deliver_one
from games.services.alert_presentation import format_message, render_card
from games.services.group_absence import report_issue


class CategoryMappingTests(SimpleTestCase):
    def test_board_partitions_and_boundaries(self):
        for _, groups in CATEGORY_FAMILIES:
            self.assertEqual(sorted(n for group in groups for n in group.numbers), list(range(28)))
        self.assertEqual([g.id for g in CATEGORIES_BY_NUMBER[18]], ['R03', 'C05', 'BE', 'middle', 'center'])
        self.assertEqual([g.id for g in CATEGORIES_BY_NUMBER[0]], ['R01', 'C01', 'SE', 'edges', 'border'])
        self.assertEqual([g.id for g in CATEGORIES_BY_NUMBER[13]], ['R02', 'C07', 'SO', 'middle', 'border'])
        self.assertEqual([g.id for g in CATEGORIES_BY_NUMBER[27]], ['R04', 'C07', 'BO', 'edges', 'border'])


@override_settings(ALERT_TELEGRAM_ENABLED=True, ALERT_TELEGRAM_BOT_TOKEN='fake-test-token', LOGGER_API_TOKEN='test')
class CategoryAlertTests(TestCase):
    def setUp(self):
        self.base = timezone.now() - timedelta(minutes=60)
        self.destination = AlertDestination.objects.create(name='Test', chat_id='123', enabled=True, use_cards=True)
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = override_settings(ALERT_STATE_DIR=Path(directory.name))
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

    def configure(self, pairs=(('R03', 'absence'), ('R03', 'streak')), threshold=3, enabled=True):
        values = {(group.id, mode): dict(enabled=(group.id, mode) in pairs, threshold=threshold)
                  for group in CATEGORIES for mode in CATEGORY_MODES}
        return save_settings('lucky28', enabled, values, 'Test operator')

    def rule(self, group='R03', mode='absence'):
        return CategoryAlertRule.objects.get(settings_id='lucky28', group_id=group, mode=mode)

    def test_new_rules_unconfigured_until_explicit_setup(self):
        config, rules = synchronize()
        self.assertFalse(config.enabled)
        self.assertEqual(len(rules), 38)
        self.assertTrue(all(not r.enabled and r.threshold is None for r in rules))

    def test_absence_three_and_reset_then_new_period(self):
        self.configure(pairs=(('R03', 'absence'),))
        self.sequence([18, 2, 7])
        self.assertEqual(CategoryAlertEvent.objects.count(), 0)
        self.result(103, 22)
        self.assertEqual(self.rule().count, 3)
        event = CategoryAlertEvent.objects.get()
        self.assertEqual(event.snapshot['numbers'], list(range(14, 21)))
        self.assertEqual(event.snapshot['last_number'], 18)
        self.result(104, 23)
        self.assertEqual(CategoryAlertEvent.objects.count(), 1)
        self.result(105, 20)
        self.assertEqual(self.rule().count, 0)
        event.refresh_from_db()
        self.assertIsNotNone(event.resolved_at)
        self.assertEqual(AlertDelivery.objects.get(kind='category').status, 'cancelled')
        self.sequence([1, 2, 3], start=106)
        self.assertEqual(CategoryAlertEvent.objects.count(), 2)

    def test_streak_counts_different_members_and_rearms_after_break(self):
        self.configure(pairs=(('R03', 'streak'),))
        self.sequence([0, 14, 19])
        self.assertEqual(CategoryAlertEvent.objects.count(), 0)
        self.result(103, 20)
        self.assertEqual(self.rule(mode='streak').count, 3)
        self.assertEqual(CategoryAlertEvent.objects.count(), 1)
        self.result(104, 16)
        synchronize()
        self.assertEqual(CategoryAlertEvent.objects.count(), 1)
        self.result(105, 21)
        self.assertEqual(self.rule(mode='streak').count, 0)
        self.sequence([15, 17, 18], start=106)
        self.assertEqual(CategoryAlertEvent.objects.count(), 2)

    def test_extreme_and_border_absence_end_on_return_with_frozen_category(self):
        self.configure(pairs=(('edges', 'absence'), ('border', 'absence'),
                              ('middle', 'streak'), ('center', 'streak')))
        self.sequence([0, 8, 9, 10])
        self.assertEqual(CategoryAlertEvent.objects.count(), 4)
        for key in ('edges', 'border'):
            event = CategoryAlertEvent.objects.get(rule__group_id=key)
            self.assertEqual(event.snapshot['count'], 3)
        self.result(104, 1)
        self.assertEqual(self.rule('edges').count, 0)
        self.assertEqual(self.rule('border').count, 0)
        self.assertFalse(CategoryAlertEvent.objects.filter(resolved_at__isnull=True).exists())
        synchronize()
        self.assertEqual(CategoryAlertEvent.objects.count(), 4)

    def test_column_and_combination_streaks_and_independent_modes(self):
        self.configure(pairs=(('C01', 'streak'), ('SE', 'streak'), ('BO', 'absence')))
        self.sequence([0, 7, 14])
        self.assertEqual(self.rule('C01', 'streak').count, 3)
        self.assertTrue(CategoryAlertEvent.objects.filter(rule__group_id='C01').exists())
        self.sequence([0, 2, 12], start=103)
        self.assertEqual(self.rule('SE', 'streak').count, 3)
        self.assertTrue(CategoryAlertEvent.objects.filter(rule__group_id='SE').exists())
        self.assertEqual(self.rule('BO').count, 6)
        self.assertEqual(CategoryAlertEvent.objects.filter(rule__group_id='BO').count(), 1)
        self.assertFalse(CategoryAlertEvent.objects.filter(rule__group_id='R01').exists())

    def test_threshold_changes_toggles_duplicate_and_restart_do_not_duplicate(self):
        self.configure(pairs=(('R03', 'streak'),), threshold=4)
        self.sequence([0, 14, 19, 20])
        self.assertEqual(CategoryAlertEvent.objects.count(), 0)
        self.configure(pairs=(('R03', 'streak'),))
        for _ in range(2):
            self.configure(pairs=(('R03', 'streak'),), enabled=False)
            self.configure(pairs=(('R03', 'streak'),), threshold=2)
            self.result(103, 20)
            synchronize()
        self.assertEqual(CategoryAlertEvent.objects.count(), 1)
        self.assertEqual(AlertDelivery.objects.filter(kind='category').count(), 1)
        self.assertTrue(CategoryAlertChange.objects.filter(editor='Test operator').exists())

    def test_gap_pauses_unknown_boundaries_but_known_hit_or_break_recovers(self):
        self.configure()
        self.result(100, 0)
        self.sequence([14, 19, 20], start=102)
        self.assertFalse(self.rule(mode='streak').complete)
        self.assertTrue(self.rule().complete)
        self.assertEqual(CategoryAlertEvent.objects.count(), 0)
        self.result(101, 2)
        self.assertTrue(self.rule(mode='streak').complete)
        self.assertEqual(CategoryAlertEvent.objects.count(), 1)
        self.result(106, 1)  # Missing 105; absence's prior hit is unknown.
        self.assertFalse(self.rule().complete)
        self.assertTrue(self.rule(mode='streak').complete)
        self.result(107, 18)
        self.assertTrue(self.rule().complete)
        self.sequence([0, 7, 21], start=108)
        self.assertEqual(self.rule().count, 3)
        self.assertEqual(CategoryAlertEvent.objects.count(), 2)

    def test_invalid_latest_and_rejected_packet_pause_without_erasing_counts(self):
        self.configure(pairs=(('R03', 'streak'),))
        self.sequence([0, 14, 19, 20])
        self.result(104, 28)
        self.assertFalse(self.rule(mode='streak').complete)
        self.assertEqual(self.rule(mode='streak').count, 3)
        self.result(104, 16, winner_event_ts=None)
        self.assertFalse(self.rule(mode='streak').complete)
        self.result(104, 16)
        report_issue('lucky28', 'R105', 'Invalid result')
        synchronize()
        self.assertFalse(self.rule(mode='streak').complete)
        self.result(105, 18)
        self.assertTrue(self.rule(mode='streak').complete)
        self.assertEqual(CategoryAlertEvent.objects.count(), 1)

    def test_correction_cancels_ended_streak_and_allows_new_one(self):
        self.configure(pairs=(('R03', 'streak'),))
        self.sequence([0, 14, 19, 20])
        self.result(103, 1)
        self.assertIsNotNone(CategoryAlertEvent.objects.get().resolved_at)
        self.assertEqual(AlertDelivery.objects.get(kind='category').status, 'cancelled')
        self.sequence([14, 19, 20], start=104)
        self.assertEqual(CategoryAlertEvent.objects.count(), 2)

    def test_history_import_does_not_replay_ended_periods_and_streams_are_isolated(self):
        self.configure(pairs=(('R03', 'streak'),))
        self.sequence([14, 19, 20, 0, 1], evaluate=False)
        synchronize()
        self.assertEqual(CategoryAlertEvent.objects.count(), 0)
        self.sequence([14, 19, 20], stream='other')
        self.assertEqual(CategoryAlertEvent.objects.count(), 0)
        self.assertFalse(CategoryAlertSettings.objects.get(pk='other').enabled)

    def test_cross_midnight_and_unseen_absence_are_lower_bound(self):
        self.base = timezone.now().replace(hour=23, minute=58, second=18, microsecond=0)
        self.configure(pairs=(('BO', 'absence'),))
        self.sequence([0, 2, 4, 6])
        self.assertEqual(self.rule('BO').count, 4)
        self.assertTrue(self.rule('BO').lower_bound)
        self.assertEqual(CategoryAlertEvent.objects.count(), 1)

    def test_event_and_delivery_rollback_together(self):
        self.configure(pairs=(('R03', 'streak'),))
        self.sequence([0, 14, 19, 20], evaluate=False)
        with patch('games.services.category_alerts.queue_delivery', side_effect=RuntimeError('simulated')):
            with self.assertRaises(RuntimeError):
                synchronize()
        self.assertEqual(CategoryAlertEvent.objects.count(), 0)
        synchronize()
        self.assertEqual(CategoryAlertEvent.objects.count(), 1)

    def test_invalid_threshold_save_is_atomic(self):
        self.configure()
        values = {(g.id, m): dict(enabled=True, threshold=3) for g in CATEGORIES for m in CATEGORY_MODES}
        for bad in ('', '1.5', '-1', '0', '1000001', 'abc'):
            values[('SO', 'streak')]['threshold'] = bad
            before = CategoryAlertChange.objects.count()
            with self.assertRaises(ValidationError):
                save_settings('lucky28', False, values, 'Bad input')
            self.assertTrue(CategoryAlertSettings.objects.get(pk='lucky28').enabled)
            self.assertEqual(CategoryAlertChange.objects.count(), before)

    @patch('games.services.alert_delivery.requests.post')
    def test_cards_and_text_show_numbers_rate_limit_retry_keeps_key(self, post):
        self.configure(pairs=(('R03', 'streak'),))
        self.sequence([0, 14, 19, 20])
        delivery = AlertDelivery.objects.get(kind='category')
        message = format_message(delivery.payload, 'category')
        self.assertIn('Row 3 [14, 15, 16, 17, 18, 19, 20]', message)
        self.assertIn('3 consecutive completed rounds', message)
        self.assertLess(len(message), 1024)
        card = render_card(delivery.payload, 'category')
        self.assertEqual(Image.open(BytesIO(card)).size[0], 1080)
        self.assertLess(len(card), 400000)
        key = delivery.dedup_key
        post.return_value = Mock(status_code=429, json=Mock(return_value={'ok': False, 'parameters': {'retry_after': 1}}))
        deliver_one(delivery.pk)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'pending')
        self.result(104, 16)
        AlertDelivery.objects.filter(pk=delivery.pk).update(available_at=timezone.now())
        post.return_value = Mock(status_code=200, json=Mock(return_value={'ok': True, 'result': {'message_id': 42}}))
        deliver_one(delivery.pk)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'sent')
        self.assertEqual(delivery.dedup_key, key)
        self.assertIn('4 consecutive completed rounds', post.call_args.kwargs['data']['caption'])
        self.assertTrue(post.call_args.args[0].endswith('/sendPhoto'))
        self.assertFalse(deliver_one(delivery.pk))

    @patch('games.services.alert_delivery.requests.post')
    def test_paused_delivery_and_uncertain_network_are_not_resent(self, post):
        self.configure(pairs=(('R03', 'streak'),))
        self.sequence([0, 14, 19, 20])
        delivery = AlertDelivery.objects.get(kind='category')
        self.configure(pairs=(('R03', 'streak'),), enabled=False)
        deliver_one(delivery.pk)
        self.assertFalse(post.called)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'pending')
        self.configure(pairs=(('R03', 'streak'),))
        AlertDelivery.objects.filter(pk=delivery.pk).update(available_at=timezone.now())
        post.side_effect = requests.Timeout()
        deliver_one(delivery.pk)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'uncertain')
        self.assertFalse(deliver_one(delivery.pk))

    def test_logger_hook_and_duplicate_winner(self):
        self.configure(pairs=(('R03', 'streak'),))
        self.sequence([0, 14, 19])
        api = APIClient()
        api.credentials(HTTP_X_LUCKY28_TOKEN='test')
        data = dict(schema_version=1, game_type='lucky28', game_no='R103', phase='winner',
                    observed_at=timezone.now().isoformat(), data=dict(winning_number=20, status=3))
        self.assertEqual(api.post('/api/logger/events/', data, format='json').status_code, 200)
        self.assertTrue(api.post('/api/logger/events/', data, format='json').json()['duplicate'])
        self.assertEqual(CategoryAlertEvent.objects.count(), 1)

    def test_management_access_validation_save_and_csrf(self):
        self.sequence([0, 14, 19, 20])
        self.assertEqual(self.client.get('/alerts/categories/').status_code, 403)
        local = dict(REMOTE_ADDR='127.0.0.1', HTTP_HOST='localhost')
        self.assertContains(self.client.get('/alerts/categories/', **local), '[14, 15, 16, 17, 18, 19, 20]')
        data = dict(enabled='on', R03_streak_enabled='on', R03_streak_threshold='1.5')
        self.assertEqual(self.client.post('/alerts/categories/settings/', data, **local).status_code, 400)
        self.assertFalse(CategoryAlertSettings.objects.get().enabled)
        data['R03_streak_threshold'] = ' 3 '
        response = self.client.post('/alerts/categories/settings/', data, follow=True, **local)
        self.assertContains(response, 'Row, column and category settings saved and applied immediately.')
        self.assertEqual(CategoryAlertEvent.objects.count(), 1)
        self.assertEqual(self.rule(mode='streak').threshold, 3)
        self.assertEqual(Client(enforce_csrf_checks=True).post('/alerts/categories/settings/', data, **local).status_code, 403)

    def mark_original_sent(self):
        original = AlertDelivery.objects.filter(kind='category').latest('pk')
        AlertDelivery.objects.filter(pk=original.pk).update(status='sent', sent_at=timezone.now(), message_id=41)
        return original

    def test_absence_ending_has_final_count_exact_breaker_and_no_count_updates(self):
        self.configure(pairs=(('R03', 'absence'),))
        self.sequence([14, 0, 7, 21])
        original = self.mark_original_sent()
        self.result(104, 1)
        self.assertFalse(AlertDelivery.objects.filter(kind='category_end').exists())
        self.result(105, 20)
        ending = AlertDelivery.objects.get(kind='category_end')
        self.assertEqual(ending.payload['count'], 4)
        self.assertEqual(ending.payload['ended_number'], 20)
        self.assertEqual(ending.payload['evaluated_round'], 'R105')
        self.assertEqual(ending.payload['original_delivery_id'], original.pk)
        self.assertEqual(ending.payload['numbers'], list(range(14, 21)))
        self.sequence([0, 7, 21], start=106)
        synchronize()
        event = CategoryAlertEvent.objects.get(pk=original.payload['event_id'])
        self.assertEqual(event.resolution_snapshot['evaluated_round'], 'R105')
        self.assertEqual(AlertDelivery.objects.filter(kind='category_end').count(), 1)

    def test_streak_ending_records_first_outsider_even_after_new_streak(self):
        self.configure(pairs=(('R03', 'streak'),))
        self.sequence([0, 14, 19, 20])
        self.mark_original_sent()
        self.result(104, 16)
        self.sequence([21, 15, 17, 18], start=105, evaluate=False)
        synchronize()
        ending = AlertDelivery.objects.get(kind='category_end')
        self.assertEqual(ending.payload['count'], 4)
        self.assertEqual(ending.payload['ended_number'], 21)
        self.assertEqual(ending.payload['evaluated_round'], 'R105')
        self.assertEqual(CategoryAlertEvent.objects.count(), 2)
        for _ in range(3):
            synchronize()
        self.assertEqual(AlertDelivery.objects.filter(kind='category_end').count(), 1)

    def test_ending_only_goes_to_confirmed_original_recipients(self):
        other = AlertDestination.objects.create(name='Other', chat_id='456', enabled=True)
        self.configure(pairs=(('R03', 'streak'),))
        self.sequence([0, 14, 19, 20])
        AlertDelivery.objects.filter(kind='category', destination=self.destination).update(status='sent', sent_at=timezone.now())
        AlertDelivery.objects.filter(kind='category', destination=other).update(status='uncertain')
        AlertDestination.objects.create(name='New', chat_id='789', enabled=True)
        self.result(104, 21)
        ending = AlertDelivery.objects.get(kind='category_end')
        self.assertEqual(ending.destination, self.destination)

    def test_original_send_finishing_after_break_still_gets_one_followup(self):
        self.configure(pairs=(('R03', 'streak'),))
        self.sequence([0, 14, 19, 20])
        AlertDelivery.objects.filter(kind='category').update(status='sending')
        self.result(104, 21)
        self.assertFalse(AlertDelivery.objects.filter(kind='category_end').exists())
        self.mark_original_sent()
        synchronize()
        synchronize()
        self.assertEqual(AlertDelivery.objects.filter(kind='category_end').count(), 1)

    def test_unchanged_ending_reuses_frozen_timeline_and_preserves_chat_id(self):
        self.destination.chat_id = '-1000123456789'
        self.destination.save()
        self.configure(pairs=(('R03', 'streak'),))
        self.sequence([0, 14, 19, 20])
        self.mark_original_sent()
        self.result(104, 21)
        ending = AlertDelivery.objects.get(kind='category_end')
        frozen = ending.payload
        with patch('games.services.card_timeline.snapshot_for_round', side_effect=AssertionError('unchanged evidence rebuilt')):
            synchronize()
            synchronize()
        ending.refresh_from_db()
        self.assertEqual(ending.payload, frozen)
        self.assertEqual(ending.payload['chat_id'], '-1000123456789')
        self.assertEqual(AlertDelivery.objects.filter(kind='category_end').count(), 1)

    def test_unsent_original_and_preexisting_resolved_events_do_not_send_endings(self):
        self.configure(pairs=(('R03', 'streak'),))
        self.sequence([0, 14, 19, 20, 21])
        self.assertFalse(AlertDelivery.objects.filter(kind='category_end').exists())
        # Simulate an event resolved before this feature's migration.
        CategoryAlertEvent.objects.update(resolution_snapshot={})
        self.mark_original_sent()
        synchronize()
        self.assertFalse(AlertDelivery.objects.filter(kind='category_end').exists())

    def test_missing_round_delays_ending_until_exact_break_can_be_verified(self):
        self.configure(pairs=(('R03', 'absence'),))
        self.sequence([14, 0, 7, 21])
        self.mark_original_sent()
        self.result(105, 20)
        self.assertFalse(AlertDelivery.objects.filter(kind='category_end').exists())
        self.result(104, 1)
        ending = AlertDelivery.objects.get(kind='category_end')
        self.assertEqual(ending.payload['count'], 4)
        self.assertEqual(ending.payload['evaluated_round'], 'R105')

    @patch('games.services.alert_delivery.requests.post')
    def test_corrected_break_cancels_queued_followup(self, post):
        self.configure(pairs=(('R03', 'streak'),))
        self.sequence([0, 14, 19, 20])
        self.mark_original_sent()
        self.result(104, 21)
        ending = AlertDelivery.objects.get(kind='category_end')
        self.result(104, 16)
        ending.refresh_from_db()
        self.assertEqual(ending.status, 'cancelled')
        self.assertIsNone(CategoryAlertEvent.objects.get().resolved_at)
        self.assertFalse(deliver_one(ending.pk))
        self.assertFalse(post.called)
        self.result(105, 21)
        ending.refresh_from_db()
        self.assertEqual(ending.status, 'pending')
        self.assertEqual(ending.payload['evaluated_round'], 'R105')
        self.assertEqual(ending.payload['count'], 4)
        self.assertEqual(AlertDelivery.objects.filter(kind='category_end').count(), 1)

    @patch('games.services.alert_delivery.requests.post')
    def test_ending_cards_retry_and_toggle_preserve_one_delivery(self, post):
        self.configure(pairs=(('R03', 'streak'),))
        self.sequence([0, 14, 19, 20])
        self.mark_original_sent()
        self.result(104, 21)
        ending = AlertDelivery.objects.get(kind='category_end')
        key = ending.dedup_key
        config = CategoryAlertSettings.objects.get()
        values = {(r.group_id, r.mode):dict(enabled=r.enabled, threshold=r.threshold) for r in config.rules.all()}
        save_settings('lucky28', True, values, 'Test operator', notify_changes=False)
        deliver_one(ending.pk)
        self.assertFalse(post.called)
        ending.refresh_from_db()
        self.assertEqual(ending.status, 'pending')
        save_settings('lucky28', True, values, 'Test operator', notify_changes=True)
        AlertDelivery.objects.filter(pk=ending.pk).update(available_at=timezone.now())
        post.return_value = Mock(status_code=429, json=Mock(return_value={'ok':False, 'parameters':{'retry_after':1}}))
        deliver_one(ending.pk)
        ending.refresh_from_db()
        self.assertEqual(ending.status, 'pending')
        AlertDelivery.objects.filter(pk=ending.pk).update(available_at=timezone.now())
        post.return_value = Mock(status_code=200, json=Mock(return_value={'ok':True, 'result':{'message_id':42}}))
        deliver_one(ending.pk)
        ending.refresh_from_db()
        self.assertEqual(ending.status, 'sent')
        self.assertEqual(ending.dedup_key, key)
        caption = post.call_args.kwargs['data']['caption']
        self.assertIn('ROW STREAK ENDED', caption)
        self.assertIn('[14, 15, 16, 17, 18, 19, 20]', caption)
        self.assertIn('after 3 consecutive hits', caption)
        self.assertIn('Result 21 is outside this group', caption)
        self.assertLess(len(caption), 1024)
        self.assertEqual(AlertDelivery.objects.filter(kind='category_end').count(), 1)
        self.assertTrue(CategoryAlertChange.objects.filter(group_id='Follow-ups', new_value__enabled=False).exists())
        self.assertFalse(deliver_one(ending.pk))

    @patch('games.services.alert_delivery.requests.post')
    def test_followup_uncertain_send_is_never_retried(self, post):
        self.configure(pairs=(('R03', 'absence'),))
        self.sequence([14, 0, 7, 21])
        self.mark_original_sent()
        self.result(104, 18)
        ending = AlertDelivery.objects.get(kind='category_end')
        post.side_effect = requests.Timeout()
        deliver_one(ending.pk)
        ending.refresh_from_db()
        self.assertEqual(ending.status, 'uncertain')
        synchronize()
        self.assertFalse(deliver_one(ending.pk))
        self.assertEqual(post.call_count, 1)

    def test_followup_switch_is_saved_and_history_shows_ending(self):
        self.configure(pairs=(('R03', 'streak'),))
        self.sequence([0, 14, 19, 20])
        self.mark_original_sent()
        self.result(104, 21)
        local = dict(REMOTE_ADDR='127.0.0.1', HTTP_HOST='localhost')
        self.assertContains(self.client.get('/alerts/categories/', **local), 'ROW STREAK ENDED')
        data = dict(enabled='on', R03_streak_enabled='on', R03_streak_threshold='3')
        self.client.post('/alerts/categories/settings/', data, **local)
        self.assertFalse(CategoryAlertSettings.objects.get().notify_changes)
        data['notify_changes'] = 'on'
        self.client.post('/alerts/categories/settings/', data, **local)
        self.assertTrue(CategoryAlertSettings.objects.get().notify_changes)
