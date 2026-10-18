from copy import deepcopy
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from games.models import (GameRound, AlertRule, AlertEvaluation, AlertOccurrence,
                          AlertDestination, AlertDelivery, AlertRuntime)
from games.services.alert_engine import evaluate_rules
from games.services.alerts import record_live_event, check_collection_health
from games.services.alert_delivery import deliver_one, recover_abandoned_claims, card_with_deadline
from games.services.alert_presentation import format_message, render_card


class RuleEngineTests(SimpleTestCase):
    def rule(self, mode='streak', **kwargs):
        return SimpleNamespace(**dict(dict(key='big', revision=1, title='Big streak', series='size', mode=mode,
            values=['Big'], breaker_value='Small', threshold=3, window=5, enabled=True,
            session_only=False, min_plan_rank=1), **kwargs))

    def test_threshold_activation_and_revision(self):
        rule = self.rule()
        self.assertEqual(evaluate_rules([rule], {'size': ['Big'] * 2}), [])
        match = evaluate_rules([rule], {'size': ['Big'] * 3})[0]
        self.assertTrue(match['is_activation'])
        self.assertFalse(evaluate_rules([rule], {'size': ['Big'] * 4}, [match['identity']])[0]['is_activation'])
        rule.revision += 1
        self.assertTrue(evaluate_rules([rule], {'size': ['Big'] * 4}, [match['identity']])[0]['is_activation'])

    def test_all_modes_and_missing_facts(self):
        cases = [
            ('absence', ['Small'] * 3, True), ('absence', ['Small', None, 'Small'], False),
            ('density', ['Big', 'Small', 'Big', 'Small', 'Big'], True),
            ('density', ['Big'] * 3, False), ('density', ['Big', None, 'Big', 'Big', 'Big'], False),
            ('density_low', ['Small'] * 5, True), ('density_low', [], False),
            ('breaker', ['Small'] + ['Big'] * 3, True), ('breaker', [None] + ['Big'] * 3, False),
            ('streak', ['Big', None, 'Big'], False),
        ]
        for mode, values, expected in cases:
            with self.subTest(mode=mode, values=values):
                self.assertEqual(bool(evaluate_rules([self.rule(mode)], {'size': values})), expected)
        alternating = self.rule('alternating', values=['Big', 'Small'], threshold=4)
        self.assertTrue(evaluate_rules([alternating], {'size': ['Big', 'Small', 'Big', 'Small']}))
        self.assertFalse(evaluate_rules([alternating], {'size': ['Big', 'Small', 'Small', 'Big']}))
        self.assertTrue(evaluate_rules([self.rule('every_game')], {}, ['big:1:global'])[0]['is_activation'])

    def test_density_matches_exact_tokens(self):
        rule = self.rule('density', values=['HIGH'], threshold=3, window=3)
        self.assertEqual(evaluate_rules([rule], {'size': ['H', 'H', 'H']}), [])


@override_settings(ALERT_TELEGRAM_ENABLED=True, ALERT_TELEGRAM_BOT_TOKEN='test-token', LOGGER_API_TOKEN='test')
class AlertIntegrationTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.rule = AlertRule.objects.create(key='big_streak', title='Big streak', series='size',
                                            mode='streak', values=['Big'], threshold=2)
        self.destination = AlertDestination.objects.create(name='Test', chat_id='123', enabled=True, send_results=True, use_cards=False)
        self.client = APIClient()
        self.client.credentials(HTTP_X_LUCKY28_TOKEN='test')
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(ALERT_STATE_DIR=Path(self.directory.name))
        self.override.enable()
        self.addCleanup(self.override.disable)

    def history(self, numbers=(14, 16)):
        for index, number in enumerate(numbers):
            GameRound.objects.create(game_no=f'history-{index}', game_type='lucky28', has_winner=True,
                winning_number=number, winner_event_ts=self.now - timedelta(seconds=60 - index * 10))

    def pre(self, name='current', seconds=0):
        game = GameRound.objects.create(game_no=name, game_type='lucky28', has_pre=True,
                                       pre_event_ts=self.now + timedelta(seconds=seconds))
        return game, record_live_event(game, 'pre')

    def event(self, game_no='current', phase='pre', observed=None, **data):
        return self.client.post('/api/logger/events/', dict(schema_version=1, game_type='lucky28',
            game_no=game_no, phase=phase, observed_at=(observed or self.now).isoformat(), data=data), format='json')

    def test_frozen_snapshot_retries_winner_and_correction(self):
        self.history()
        self.assertEqual(self.event(rate_big=75).status_code, 200)
        evaluation = AlertEvaluation.objects.get()
        frozen = deepcopy(evaluation.evidence)
        self.event(observed=self.now + timedelta(seconds=1), rate_big=10)
        self.event(phase='winner', observed=self.now + timedelta(seconds=2), winning_number=1, status=3)
        self.event(phase='winner', observed=self.now + timedelta(seconds=3), winning_number=1, status=3)
        self.assertEqual(AlertEvaluation.objects.count(), 1)
        self.assertEqual(AlertOccurrence.objects.count(), 1)
        evaluation.refresh_from_db()
        self.assertEqual(evaluation.evidence, frozen)
        self.assertEqual(evaluation.evidence['rates']['rate_big'], '75.00')
        self.assertEqual(AlertDelivery.objects.filter(kind='alert').count(), 1)
        self.assertEqual(AlertDelivery.objects.filter(kind='result').count(), 1)

    def test_active_condition_rearms_after_break_and_revision(self):
        self.history()
        _, first = self.pre()
        _, second = self.pre('second', 1)
        self.assertTrue(first.occurrences.get().is_activation)
        self.assertFalse(second.occurrences.get().is_activation)
        self.rule.threshold = 1
        self.rule.save()
        _, third = self.pre('third', 2)
        self.assertTrue(third.occurrences.get().is_activation)
        GameRound.objects.create(game_no='break', game_type='lucky28', has_winner=True, winning_number=1,
                                 winner_event_ts=self.now + timedelta(seconds=2.5))
        _, fourth = self.pre('fourth', 3)
        self.assertEqual(fourth.active_keys, [])
        GameRound.objects.create(game_no='new-big', game_type='lucky28', has_winner=True, winning_number=14,
                                 winner_event_ts=self.now + timedelta(seconds=3.5))
        _, fifth = self.pre('fifth', 4)
        self.assertTrue(fifth.occurrences.get().is_activation)

    def test_future_and_other_game_results_excluded_history_order(self):
        self.history()
        GameRound.objects.create(game_no='future', winning_number=1, has_winner=True, winner_event_ts=self.now + timedelta(seconds=2))
        GameRound.objects.create(game_no='race', game_type='luckyrace', winning_number=1, has_winner=True, winner_event_ts=self.now - timedelta(seconds=1))
        _, evaluation = self.pre()
        self.assertEqual(evaluation.evidence['history_count'], 2)
        self.assertEqual([r['number'] for r in evaluation.evidence['timeline']], [16, 14])

    def test_old_replay_winner_first_and_late_round_do_not_evaluate(self):
        self.event('old', observed=self.now - timedelta(days=1))
        self.event('winner-first', phase='winner', winning_number=0, status=3)
        self.event('winner-first', observed=self.now + timedelta(seconds=1))
        self.assertEqual(AlertEvaluation.objects.count(), 0)
        self.pre()
        _, late = self.pre('late', -1)
        self.assertIsNone(late)
        self.assertEqual(AlertEvaluation.objects.count(), 1)

    def test_session_rules_exclude_previous_epoch(self):
        self.history()
        self.rule.session_only = True
        self.rule.save()
        with override_settings(SERVER_SESSION_STARTED_AT=self.now - timedelta(seconds=5)):
            _, evaluation = self.pre()
        self.assertEqual(evaluation.active_keys, [])

    def test_rank_and_expiry_routing(self):
        self.history()
        self.rule.min_plan_rank = 3
        self.rule.save()
        allowed = AlertDestination.objects.create(name='Gold', chat_id='456', enabled=True, plan_rank=3)
        AlertDestination.objects.create(name='Expired', chat_id='789', enabled=True, plan_rank=5, expires_at=self.now - timedelta(seconds=1))
        self.pre()
        self.assertEqual(AlertDelivery.objects.get().destination_id, allowed.pk)

    @override_settings(ALERT_TELEGRAM_ENABLED=False)
    def test_disabled_delivery_keeps_local_evidence(self):
        self.history()
        _, evaluation = self.pre()
        self.assertEqual(evaluation.occurrences.count(), 1)
        self.assertFalse(AlertDelivery.objects.exists())

    def test_rule_validation_and_seed_preserves_customization(self):
        self.rule.window = 2
        self.rule.mode = 'density'
        self.rule.threshold = 3
        with self.assertRaises(ValidationError):
            self.rule.save()
        call_command('seed_alert_rules', stdout=BytesIOText())
        rule = AlertRule.objects.get(key='number_0_drought')
        rule.threshold = 70
        rule.save()
        call_command('seed_alert_rules', stdout=BytesIOText())
        self.assertEqual(AlertRule.objects.get(pk=rule.pk).threshold, 70)

    def test_health_warning_rearms_only_after_fresh_ingestion(self):
        check_collection_health(self.now)
        check_collection_health(self.now + timedelta(minutes=3))
        check_collection_health(self.now + timedelta(minutes=4))
        self.assertEqual(AlertDelivery.objects.filter(kind='health').count(), 1)
        self.event('old', observed=self.now - timedelta(days=1))
        self.assertTrue(AlertRuntime.objects.get().outage_active)
        self.event()
        self.assertFalse(AlertRuntime.objects.get().outage_active)
        check_collection_health(self.now + timedelta(minutes=5))
        self.assertEqual(AlertDelivery.objects.filter(kind='health').count(), 2)

    def test_pages_evidence_and_anonymous_configuration_access(self):
        self.history()
        _, evaluation = self.pre()
        self.assertContains(self.client.get('/alerts/'), 'Big streak')
        self.assertEqual(self.client.get(f'/alerts/evidence/{evaluation.pk}/').json(), evaluation.evidence)
        self.assertEqual(self.client.get('/api/alerts/latest/').json()['evaluation_id'], evaluation.pk)
        self.assertEqual(self.client.get('/admin/games/alertrule/').status_code, 302)

    @patch('games.services.whatsapp.WhatsAppService')
    @patch('games.services.signals.SignalAnalyzer')
    def test_legacy_endpoints_capture_alerts_and_parse_timestamp_strings(self, analyze, whatsapp):
        self.history()
        response = self.client.post('/api/games/pre/', dict(game_no='legacy', pre_event_ts=self.now.isoformat()), format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(AlertEvaluation.objects.get().game_no, 'legacy')
        response = self.client.patch('/api/games/legacy/winner/', dict(winning_number=0,
            winner_event_ts=(self.now + timedelta(seconds=1)).isoformat()), format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AlertDelivery.objects.get(kind='result').payload['result']['number'], 0)

    def test_game_deletion_preserves_frozen_evidence(self):
        self.history()
        game, evaluation = self.pre()
        frozen = deepcopy(evaluation.evidence)
        game.delete()
        evaluation.refresh_from_db()
        self.assertIsNone(evaluation.game_id)
        self.assertEqual(evaluation.evidence, frozen)

    @patch('games.services.alert_delivery.requests.post')
    def test_resumed_collection_cancels_queued_warning(self, post):
        check_collection_health(self.now)
        check_collection_health(self.now + timedelta(minutes=3))
        warning = AlertDelivery.objects.get(kind='health')
        self.event()
        deliver_one(warning.pk)
        warning.refresh_from_db()
        self.assertEqual(warning.status, 'cancelled')
        post.assert_not_called()

    @patch('games.services.alert_delivery.requests.post')
    def test_render_failure_sends_text_and_completed_during_render_cancels(self, post):
        delivery = self.delivery()
        delivery.payload['use_cards'] = True
        delivery.save()
        post.return_value = Mock(status_code=200, json=lambda: {'ok': True, 'result': {'message_id': 42}})
        with patch('games.services.alert_delivery.card_with_deadline', return_value=None):
            deliver_one(delivery.pk)
        self.assertTrue(post.call_args.args[0].endswith('/sendMessage'))
        post.reset_mock()
        AlertDelivery.objects.filter(pk=delivery.pk).update(status='pending')
        def complete(*args):
            GameRound.objects.filter(game_no='current').update(has_winner=True)
            return None
        with patch('games.services.alert_delivery.card_with_deadline', side_effect=complete):
            deliver_one(delivery.pk)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'cancelled')
        post.assert_not_called()

    @override_settings(ALERT_TELEGRAM_ENABLED=False)
    @patch('games.services.alert_delivery.requests.post')
    def test_worker_once_records_heartbeat_without_sending(self, post):
        call_command('run_alert_messaging', once=True, stdout=BytesIOText())
        runtime = AlertRuntime.objects.get()
        self.assertIsNotNone(runtime.heartbeat_at)
        self.assertEqual(runtime.worker_status, 'stopped')
        post.assert_not_called()

    def delivery(self):
        self.history()
        self.pre()
        return AlertDelivery.objects.get(kind='alert')

    @patch('games.services.alert_delivery.requests.post')
    def test_claim_sends_once_and_archives_exact_payload(self, post):
        delivery = self.delivery()
        post.return_value = Mock(status_code=200, json=lambda: {'ok': True, 'result': {'message_id': 42}})
        self.assertTrue(deliver_one(delivery.pk))
        self.assertFalse(deliver_one(delivery.pk))
        delivery.refresh_from_db()
        self.assertEqual((delivery.status, delivery.attempts, delivery.message_id), ('sent', 1, 42))
        self.assertTrue(Path(delivery.artifact_path).exists())
        post.assert_called_once()

    @patch('games.services.alert_delivery.requests.post', side_effect=requests.Timeout('secret URL'))
    def test_timeout_is_uncertain_and_never_retried(self, post):
        delivery = self.delivery()
        deliver_one(delivery.pk)
        deliver_one(delivery.pk)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'uncertain')
        self.assertNotIn('secret', delivery.error)
        post.assert_called_once()

    @patch('games.services.alert_delivery.requests.post')
    def test_http_errors_rate_limit_and_malformed_success(self, post):
        delivery = self.delivery()
        cases = [(500, {}, 'uncertain'), (403, {'ok': False}, 'failed'),
                 (200, {'ok': True}, 'uncertain'), (200, [], 'uncertain'),
                 (429, {'ok': False, 'parameters': {'retry_after': 10}}, 'pending')]
        for code, body, expected in cases:
            with self.subTest(code=code, body=body):
                AlertDelivery.objects.filter(pk=delivery.pk).update(status='pending', available_at=timezone.now())
                post.return_value = Mock(status_code=code, json=lambda: body)
                deliver_one(delivery.pk)
                delivery.refresh_from_db()
                self.assertEqual(delivery.status, expected)
        self.assertGreater(delivery.available_at, timezone.now())

    @patch('games.services.alert_delivery.requests.post')
    def test_completed_round_and_expired_subscription_cancel(self, post):
        delivery = self.delivery()
        GameRound.objects.filter(game_no='current').update(has_winner=True)
        deliver_one(delivery.pk)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'cancelled')
        GameRound.objects.filter(game_no='current').update(has_winner=False)
        AlertDelivery.objects.filter(pk=delivery.pk).update(status='pending')
        self.destination.expires_at = self.now - timedelta(seconds=1)
        self.destination.save()
        deliver_one(delivery.pk)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'cancelled')
        post.assert_not_called()

    def test_crashed_claim_is_never_requeued(self):
        delivery = self.delivery()
        AlertDelivery.objects.filter(pk=delivery.pk).update(status='sending')
        self.assertEqual(recover_abandoned_claims(), 1)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'uncertain')

    @patch('games.services.alert_delivery.requests.post')
    def test_result_followup_uses_separate_frozen_payload(self, post):
        delivery = self.delivery()
        frozen = deepcopy(delivery.payload)
        post.return_value = Mock(status_code=200, json=lambda: {'ok': True, 'result': {'message_id': 42}})
        deliver_one(delivery.pk)
        self.event(phase='winner', observed=self.now + timedelta(seconds=1), winning_number=0, status=3)
        result = AlertDelivery.objects.get(kind='result')
        self.assertEqual(result.payload['result']['number'], 0)
        deliver_one(result.pk)
        result.refresh_from_db()
        self.assertEqual(result.status, 'sent')
        delivery.refresh_from_db()
        self.assertEqual(delivery.payload, frozen)


class BytesIOText:
    def write(self, text):
        pass


class PresentationTests(SimpleTestCase):
    def payload(self):
        return dict(game_no='<round&>', captured_at=timezone.now().isoformat(),
                    matches=[dict(title='<b>Big & Small</b>', detail='Big occurred in 6 consecutive rounds.', group='size') for _ in range(100)],
                    timeline=[dict(number=n % 28, size='Big') for n in range(50)])

    def test_telegram_html_is_escaped_and_bounded(self):
        for limit in (1024, 4096):
            message = format_message(self.payload(), limit=limit)
            self.assertLessEqual(len(message.encode('utf-16-le')) // 2, limit)
            self.assertIn('&lt;round&amp;&gt;', message)
            self.assertIn('&lt;b&gt;', message)
            self.assertEqual(message.count('<b>'), message.count('</b>'))

    def test_card_dimensions_size_and_render_failure_fallback(self):
        from PIL import Image
        card = render_card(self.payload())
        self.assertLess(len(card), 400_000)
        self.assertEqual(Image.open(BytesIO(card)).width, 1080)
        with patch('games.services.alert_delivery.render_card', side_effect=RuntimeError('render failed')):
            self.assertIsNone(card_with_deadline(self.payload(), 'alert'))

    def test_card_timeout_does_not_queue_more_work(self):
        future = Mock()
        future.done.return_value = False
        with patch('games.services.alert_delivery._render_future', future), patch('games.services.alert_delivery._render_pool.submit') as submit:
            self.assertIsNone(card_with_deadline(self.payload(), 'alert'))
            submit.assert_not_called()
