from copy import deepcopy
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from games.alert_forms import AlertRuleForm
from games.models import AlertRule, AlertDelivery, AlertDestination, GameRound
from games.services.alert_engine import evaluate_rules, tip_rules
from games.services.alerts import record_live_event, game_facts
from games.services.alert_card import card_model, TIP_GOLD
from games.services.alert_presentation import format_message, render_card
from games.services.card_timeline import snapshot_from_games, snapshot_for_round
from games.services.timeline import build_timeline
from games.services.tips import tip_facts


class TipAlertTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.rules = [AlertRule.objects.create(**definition) for definition in tip_rules()]

    def history(self, tips, start=1):
        games = []
        for sequence, tip in enumerate(tips, start):
            games.append(GameRound.objects.create(game_no=f'20261027{sequence:04}', game_type='lucky28',
                has_winner=True, status=3, winning_number=sequence % 28,
                winner_event_ts=self.now-timedelta(seconds=100-sequence),
                winner_raw=dict(status=3, bet_total_energy=1000, win_total_energy=900 if tip else 1000)))
        return list(reversed(games))

    def matches(self, games):
        return evaluate_rules(self.rules, game_facts(games))

    def test_absence_three_triggers_once_until_tip_clears_it(self):
        rule = self.rules[0]
        self.assertEqual(evaluate_rules([rule], {'tip': ['NO_TIP']*2}), [])
        event = evaluate_rules([rule], {'tip': ['NO_TIP']*3})[0]
        self.assertTrue(event['is_activation'])
        self.assertEqual(event['observed'], 3)
        self.assertFalse(evaluate_rules([rule], {'tip': ['NO_TIP']*4}, [event['identity']])[0]['is_activation'])
        self.assertEqual(evaluate_rules([rule], {'tip': ['TIP', 'NO_TIP', 'NO_TIP']}, [event['identity']]), [])
        self.assertTrue(evaluate_rules([rule], {'tip': ['NO_TIP']*3 + ['TIP']}, [])[0]['is_activation'])

    def test_low_density_includes_zero_and_three_but_not_four_or_nine_rounds(self):
        rule = self.rules[1]
        for count in range(11):
            facts = {'tip': ['TIP']*count + ['NO_TIP']*(10-count)}
            matches = evaluate_rules([rule], facts)
            self.assertEqual(bool(matches), count <= 3)
            if matches:
                self.assertEqual(matches[0]['observed'], count)
                self.assertFalse(evaluate_rules([rule], facts, [matches[0]['identity']])[0]['is_activation'])
        self.assertEqual(evaluate_rules([rule], {'tip': ['NO_TIP']*9}), [])

    def test_missing_invalid_or_incomplete_round_never_counts_as_no_tip(self):
        games = self.history([False]*10)
        self.assertEqual(len(self.matches(games)), 2)
        for raw in ({'win_total_energy': 1000}, {'bet_total_energy': 1000, 'win_total_energy': 1001},
                    {'bet_total_energy': 1000, 'win_total_energy': 1000, 'totals_complete': False}):
            with self.subTest(raw=raw):
                games[0].winner_raw = raw
                self.assertEqual(self.matches(games), [])
        games[0].refresh_from_db()
        self.assertEqual(len(tip_facts(games[:2]+games[3:])), 2)
        self.assertEqual(self.matches(games[:2]+games[3:]), [])
        upcoming = GameRound(game_no='202610270012')
        self.assertEqual(tip_facts(games, upcoming), [])

    def test_daily_boundary_breaks_density_and_invalid_counts_break_absence(self):
        games = self.history([False]*10)
        games[0].game_no = '202610280001'
        self.assertEqual(tip_facts(games), ['NO_TIP'])
        self.assertEqual(self.matches(games), [])
        games[0].refresh_from_db()
        games[1].winner_raw.update(bet_users=1, winner_count=2)
        self.assertEqual(self.matches(games), [])

    def test_defaults_install_idempotently_preserving_customization_and_form_support(self):
        call_command('sync_tip_alerts', verbosity=0)
        self.assertEqual(AlertRule.objects.count(), 2)
        self.rules[0].threshold = 4
        self.rules[0].save()
        call_command('sync_tip_alerts', verbosity=0)
        self.rules[0].refresh_from_db()
        self.assertEqual(self.rules[0].threshold, 4)
        form = AlertRuleForm(data=dict(title='TIP density', series='tip', mode='density_low',
            values=['TIP'], threshold=3, window=10, min_plan_rank=1, enabled='on'))
        self.assertTrue(form.is_valid(), form.errors)

    @override_settings(ALERT_TELEGRAM_ENABLED=True, ALERT_TELEGRAM_BOT_TOKEN='test-only')
    def test_live_rule_uses_existing_destination_queue_and_frozen_tip_markers(self):
        self.history([True, False, False, True, False, False, True, False, False, False])
        destination = AlertDestination.objects.create(name='Basic', chat_id='123', enabled=True, use_cards=True)
        pending = GameRound.objects.create(game_no='202610270011', game_type='lucky28',
            has_pre=True, pre_event_ts=self.now)
        with TemporaryDirectory() as directory, override_settings(ALERT_STATE_DIR=Path(directory)):
            evaluation = record_live_event(pending, 'pre')
            record_live_event(pending, 'pre')
        deliveries = list(AlertDelivery.objects.filter(evaluation=evaluation, destination=destination))
        self.assertEqual(len(deliveries), 2)
        self.assertEqual({d.payload['matches'][0]['rule_key'] for d in deliveries}, {'tip_absence_3', 'tip_density_low_10'})
        for delivery in deliveries:
            snapshot = delivery.payload['global_timeline']
            self.assertEqual(snapshot['tip_summary']['tip_count'], 3)
            self.assertEqual(sum(g['tip']['status'] == 'TIP' for g in snapshot['games']), 3)
            caption = format_message(delivery.payload, limit=1024)
            self.assertIn('★', caption)
            self.assertIn(delivery.payload['matches'][0]['title'], caption)
            self.assertLessEqual(len(caption.encode('utf-16-le'))//2, 1024)
            self.assertEqual(card_model(delivery.payload, 'alert')['accent'], TIP_GOLD)

    def test_browser_snapshot_card_and_caption_agree_and_render_without_reads(self):
        games = self.history([False, True, False, True, False, False, True, False, False, False])
        live = build_timeline('lucky28', ['number', 'row'])
        snapshot = snapshot_for_round('lucky28', games[0].game_no)
        self.assertEqual([g['tip'] for g in live['games']], [g['tip'] for g in snapshot['games']])
        payload = dict(game_no='202610270011', captured_at='now', matches=[], global_timeline=snapshot)
        with self.assertNumQueries(0):
            marked = render_card(payload)
        self.assertEqual(Image.open(BytesIO(marked)).width, 1080)
        caption = format_message(payload)
        self.assertIn('7★', caption)
        self.assertNotIn('10★', caption)
        self.assertIn('TIP density: 3/10', caption)
        GameRound.objects.filter(pk=games[3].pk).update(winner_raw={})
        with self.assertNumQueries(0):
            self.assertEqual(marked, render_card(payload))
        plain = deepcopy(payload)
        for game in plain['global_timeline']['games']:
            game['tip']['status'] = 'NO_TIP'
        self.assertNotEqual(marked, render_card(plain))

    def test_legacy_snapshots_do_not_invent_tip_status(self):
        payload = dict(game_no='old', captured_at='then', matches=[], global_timeline={'games':[dict(number=12)]})
        self.assertNotIn('★', format_message(payload))
        self.assertNotIn('TIP density:', format_message(payload))

    def test_gold_marker_preserves_gap_dashes(self):
        payload = dict(game_no='next', matches=[], global_timeline={'games':[
            dict(number=7, tip={'status':'TIP'}, gap_before=False)]})
        solid = render_card(payload)
        payload['global_timeline']['games'][0]['gap_before'] = True
        self.assertNotEqual(solid, render_card(payload))
