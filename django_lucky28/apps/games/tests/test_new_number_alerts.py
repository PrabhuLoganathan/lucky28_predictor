from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from games.models import AlertDelivery, AlertDestination, AlertRule, GameRound
from games.services.alert_engine import evaluate_rules, new_number_rules
from games.services.alerts import game_facts, record_live_event


class NewNumberAlertsTests(TestCase):
    def setUp(self):
        self.rules = [AlertRule.objects.create(**rule) for rule in new_number_rules()]

    def test_thresholds_and_rearming(self):
        streak, density = self.rules
        self.assertFalse(evaluate_rules([streak], {'new_repeat': ['New'] * 4}))
        event = evaluate_rules([streak], {'new_repeat': ['New'] * 5})[0]
        self.assertFalse(evaluate_rules([streak], {'new_repeat': ['New'] * 6}, [event['identity']])[0]['is_activation'])
        self.assertFalse(evaluate_rules([streak], {'new_repeat': ['Repeated'] + ['New'] * 5}))
        self.assertFalse(evaluate_rules([density], {'new_repeat': ['New'] * 10 + ['Repeated'] * 5}))
        self.assertTrue(evaluate_rules([density], {'new_repeat': ['New'] * 11 + ['Repeated'] * 4}))
        self.assertFalse(evaluate_rules([density], {'new_repeat': ['New'] * 14}))
        self.assertFalse(evaluate_rules([density], {'new_repeat': ['New'] * 14 + [None]}))

    def test_facts_compare_previous_ten_and_gaps_are_unknown(self):
        now = timezone.now()
        history = [GameRound(game_no=f'R{i:03}', winning_number=i % 28,
                             winner_event_ts=now - timedelta(seconds=25-i)) for i in range(25, 0, -1)]
        facts = game_facts(history, GameRound(game_no='R026'))['new_repeat']
        self.assertEqual(facts[:15], ['New'] * 15)
        history[0].winning_number = history[1].winning_number
        self.assertEqual(game_facts(history)['new_repeat'][0], 'Repeated')
        self.assertEqual(game_facts(history, GameRound(game_no='R027'))['new_repeat'], [])
        history.pop(3)
        self.assertIsNone(game_facts(history)['new_repeat'][0])

    def test_channel_is_isolated_and_existing_chats_rejected(self):
        old = AlertDestination.objects.create(name='Existing', chat_id='old', enabled=True)
        with self.assertRaises(CommandError):
            call_command('sync_new_number_alerts', chat_id=old.chat_id, verbosity=0)
        call_command('sync_new_number_alerts', chat_id='-100123456', verbosity=0)
        dest = AlertDestination.objects.get(chat_id='-100123456')
        self.assertEqual(dest.routing_type, 'direct')
        self.assertFalse(dest.send_health or dest.send_results)
        for rule in AlertRule.objects.filter(pk__in=[r.pk for r in self.rules]):
            self.assertFalse(rule.send_to_levels)
            self.assertEqual(list(rule.destinations.all()), [dest])

    @override_settings(ALERT_TELEGRAM_ENABLED=True, ALERT_TELEGRAM_BOT_TOKEN='test-only')
    def test_live_evaluation_queues_only_to_dedicated_channel(self):
        now = timezone.now()
        for i in range(1, 26):
            GameRound.objects.create(game_no=f'R{i:03}', game_type='lucky28', has_winner=True,
                status=3, winning_number=i % 28, winner_event_ts=now - timedelta(seconds=30-i))
        AlertDestination.objects.create(name='Existing', chat_id='old', enabled=True)
        call_command('sync_new_number_alerts', chat_id='-100123456', verbosity=0)
        upcoming = GameRound.objects.create(game_no='R026', game_type='lucky28', has_pre=True, pre_event_ts=now)
        with TemporaryDirectory() as directory, override_settings(ALERT_STATE_DIR=Path(directory)):
            evaluation = record_live_event(upcoming, 'pre')
        deliveries = AlertDelivery.objects.filter(evaluation=evaluation, kind='alert')
        self.assertEqual(deliveries.count(), 2)
        self.assertEqual(set(deliveries.values_list('destination__chat_id', flat=True)), {'-100123456'})
        self.assertEqual({d.payload['matches'][0]['rule_key'] for d in deliveries},
                         {'new_number_streak_5', 'new_number_density_15'})
