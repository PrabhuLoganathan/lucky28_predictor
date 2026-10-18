from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, Client, override_settings
from django.utils import timezone

from games.models import AlertRule, AlertDestination, AlertSettings, AlertDelivery, AlertRuntime, GameRound, AlertEvaluation
from games.services.alert_settings import get_config, save_token
from games.services.alerts import record_live_event


@override_settings(ALERT_TELEGRAM_ENABLED=False, ALERT_TELEGRAM_BOT_TOKEN='')
class AlertManagementTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        override = override_settings(ALERT_STATE_DIR=Path(self.directory.name))
        override.enable()
        self.addCleanup(override.disable)
        self.client = Client(HTTP_HOST='localhost')

    def rule_data(self, **changes):
        return dict(dict(title='Big streak', series='size', mode='streak', values=['Big'], threshold=3,
                         min_plan_rank=1, enabled='on'), **changes)

    def destination(self):
        return AlertDestination.objects.create(name='My channel', chat_id='-10012345', enabled=True)

    def test_navigation_and_all_management_pages_without_admin(self):
        for url in ['/alerts/', '/alerts/rules/', '/alerts/rules/new/', '/alerts/destinations/',
                    '/alerts/destinations/new/', '/alerts/settings/', '/alerts/deliveries/']:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, '/admin/')
                self.assertContains(response, 'Telegram &amp; worker')

    def test_rule_create_edit_toggle_delete_and_revision(self):
        response = self.client.post('/alerts/rules/new/', self.rule_data())
        self.assertEqual(response.status_code, 302)
        rule = AlertRule.objects.get()
        self.assertEqual((rule.values, rule.window), (['Big'], 0))
        response = self.client.post(f'/alerts/rules/{rule.pk}/edit/', self.rule_data(threshold=4))
        self.assertEqual(response.status_code, 302)
        rule.refresh_from_db()
        self.assertEqual(rule.revision, 2)
        self.client.post(f'/alerts/rules/{rule.pk}/toggle/', {'enabled': '0'})
        rule.refresh_from_db()
        self.assertFalse(rule.enabled)
        self.assertEqual(self.client.get(f'/alerts/rules/{rule.pk}/delete/').status_code, 200)
        self.assertTrue(AlertRule.objects.exists())
        self.client.post(f'/alerts/rules/{rule.pk}/delete/')
        self.assertFalse(AlertRule.objects.exists())

    def test_rule_forms_validate_missing_and_incompatible_inputs(self):
        for changes in [{'threshold': ''}, {'values': ['Odd']}, {'mode': 'alternating', 'values': ['Big']},
                        {'mode': 'density', 'window': ''}, {'mode': 'density', 'threshold': 5, 'window': 3},
                        {'mode': 'breaker', 'breaker_value': 'Big'}]:
            with self.subTest(changes=changes):
                response = self.client.post('/alerts/rules/new/', self.rule_data(**changes))
                self.assertEqual(response.status_code, 400)
                self.assertFalse(AlertRule.objects.exists())
        response = self.client.post('/alerts/rules/new/', self.rule_data(mode='every_game', threshold='', values=[]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AlertRule.objects.get().threshold, 1)

    def test_defaults_and_filters_keep_existing_edits(self):
        self.client.post('/alerts/rules/defaults/')
        self.assertEqual(AlertRule.objects.count(), 79)
        rule = AlertRule.objects.get(key='number_0_drought')
        rule.threshold = 70
        rule.save()
        self.client.post('/alerts/rules/defaults/')
        rule.refresh_from_db()
        self.assertEqual(rule.threshold, 70)
        response = self.client.get('/alerts/rules/?q=Number+0&series=number&enabled=1')
        self.assertContains(response, 'Number 0 drought')
        self.assertNotContains(response, 'Number 1 drought')

    def test_destination_create_update_toggle_and_protected_delete(self):
        data = dict(name='Test channel', chat_id='@my_channel', plan_rank=3, enabled='on',
                    expires_at='2027-01-01T12:00', use_cards='on')
        response = self.client.post('/alerts/destinations/new/', data)
        self.assertEqual(response.status_code, 302)
        destination = AlertDestination.objects.get()
        self.assertEqual(destination.expires_at.hour, 12)
        self.assertEqual(destination.plan_rank, 3)
        self.assertEqual(self.client.get(f'/alerts/destinations/{destination.pk}/edit/').status_code, 200)
        self.client.post(f'/alerts/destinations/{destination.pk}/edit/', dict(data, name='Updated'))
        self.client.post(f'/alerts/destinations/{destination.pk}/toggle/', {'enabled': '0'})
        destination.refresh_from_db()
        self.assertEqual(destination.name, 'Updated')
        self.assertFalse(destination.enabled)
        AlertDelivery.objects.create(destination=destination, kind='test', dedup_key='test', payload={})
        self.client.post(f'/alerts/destinations/{destination.pk}/delete/')
        self.assertTrue(AlertDestination.objects.filter(pk=destination.pk, enabled=False).exists())
        AlertDelivery.objects.all().delete()
        self.client.post(f'/alerts/destinations/{destination.pk}/delete/')
        self.assertFalse(AlertDestination.objects.exists())

    def test_invalid_destination_is_rejected(self):
        response = self.client.post('/alerts/destinations/new/', dict(name='Bad', chat_id='https://example.com', plan_rank=7))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AlertDestination.objects.exists())

    def test_settings_token_is_private_masked_and_applies_without_restart(self):
        token = '123456789:' + 'x' * 30
        response = self.client.post('/alerts/settings/', dict(telegram_enabled='on', bot_token=token,
            collection_timeout_minutes=5, max_event_age_seconds=180))
        self.assertEqual(response.status_code, 302)
        config = get_config()
        self.assertTrue(config.telegram_enabled)
        self.assertEqual(config.bot_token, token)
        self.assertEqual(config.max_event_age_seconds, 180)
        self.assertNotIn(token, repr(config))
        token_file = Path(self.directory.name) / 'bot-token'
        self.assertEqual(token_file.stat().st_mode & 0o777, 0o600)
        response = self.client.get('/alerts/settings/')
        self.assertNotContains(response, token)
        self.assertContains(response, 'Saved')
        response = self.client.post('/alerts/settings/', dict(telegram_enabled='on', bot_token='',
            collection_timeout_minutes=6, max_event_age_seconds=200))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(get_config().bot_token, token)
        response = self.client.post('/alerts/settings/', dict(clear_token='on', collection_timeout_minutes=3, max_event_age_seconds=120))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(get_config().bot_token, '')
        self.assertFalse(get_config().telegram_enabled)

    def test_missing_token_blocks_enabling_and_invalid_form_does_not_expose_token(self):
        token = '123456789:' + 'z' * 30
        response = self.client.post('/alerts/settings/', dict(telegram_enabled='on', collection_timeout_minutes=3, max_event_age_seconds=120))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AlertSettings.objects.exists())
        response = self.client.post('/alerts/settings/', dict(bot_token=token, collection_timeout_minutes=0, max_event_age_seconds=120))
        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, token, status_code=400)
        self.assertEqual(get_config().bot_token, '')

    def test_environment_fallback_and_removal_override(self):
        with override_settings(ALERT_TELEGRAM_ENABLED=True, ALERT_TELEGRAM_BOT_TOKEN='environment-token'):
            self.assertEqual(get_config().bot_token, 'environment-token')
            save_token('')
            self.assertEqual(get_config().bot_token, '')
            AlertSettings.objects.create(telegram_enabled=False)
            self.assertFalse(get_config().telegram_enabled)

    @patch('games.alert_management.start_worker', return_value=True)
    def test_worker_controls_use_post_and_cooperative_stop(self, start):
        self.assertEqual(self.client.get('/alerts/worker/start/').status_code, 405)
        self.assertEqual(self.client.post('/alerts/worker/start/').status_code, 302)
        start.assert_called_once()
        self.client.post('/alerts/worker/stop/')
        self.assertTrue(AlertRuntime.objects.get().stop_requested)

    @patch('games.services.alert_delivery.requests.post')
    def test_test_message_is_queued_only_after_explicit_post(self, post):
        destination = self.destination()
        url = f'/alerts/destinations/{destination.pk}/test/'
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url)
        self.assertFalse(AlertDelivery.objects.exists())
        save_token('123456:' + 'x' * 30)
        AlertSettings.objects.create(telegram_enabled=True)
        self.client.post(url)
        delivery = AlertDelivery.objects.get()
        self.assertEqual(delivery.kind, 'test')
        self.assertEqual(delivery.payload['chat_id'], destination.chat_id)
        post.assert_not_called()
        self.assertEqual(self.client.get(f'/alerts/deliveries/{delivery.pk}/').status_code, 200)

    def test_delivery_actions_do_not_resend_uncertain_or_sent_messages(self):
        destination = self.destination()
        delivery = AlertDelivery.objects.create(destination=destination, kind='test', dedup_key='test', status='uncertain',
            payload=dict(game_no='Test', captured_at='', matches=[], chat_id='123', detail='Test message'))
        url = f'/alerts/deliveries/{delivery.pk}'
        self.client.post(url + '/retry/')
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'uncertain')
        self.assertNotContains(self.client.get(url + '/'), 'Retry failed delivery')
        AlertDelivery.objects.filter(pk=delivery.pk).update(status='failed')
        self.client.post(url + '/retry/')
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'pending')
        self.client.post(url + '/cancel/')
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'cancelled')
        self.assertContains(self.client.get('/alerts/deliveries/?status=cancelled'), '#1' if delivery.pk == 1 else f'#{delivery.pk}')

    def test_remote_access_and_csrf_protect_management(self):
        response = self.client.get('/alerts/settings/', REMOTE_ADDR='10.0.0.1')
        self.assertEqual(response.status_code, 403)
        response = self.client.get('/alerts/settings/', HTTP_HOST='attacker.example')
        self.assertEqual(response.status_code, 403)
        csrf_client = Client(enforce_csrf_checks=True, HTTP_HOST='localhost')
        self.assertEqual(csrf_client.post('/alerts/rules/defaults/').status_code, 403)
        user = get_user_model().objects.create_user(username='staff', is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get('/alerts/settings/', REMOTE_ADDR='10.0.0.1').status_code, 200)

    def test_readable_evidence_page_keeps_original_json(self):
        game = GameRound.objects.create(game_no='ui-test', game_type='lucky28', has_pre=True, pre_event_ts=timezone.now())
        evaluation = record_live_event(game, 'pre')
        response = self.client.get(f'/alerts/history/{evaluation.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Round ui-test')
        self.assertContains(response, 'Preview card')
        self.assertEqual(self.client.get(f'/alerts/evidence/{evaluation.pk}/').json(), evaluation.evidence)
