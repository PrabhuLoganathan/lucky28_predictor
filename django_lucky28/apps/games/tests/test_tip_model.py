from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from games.models import GameRound, TipStream, TipRound, TipEvent, AlertDestination
from games.services import tip_model as model, tips
from games.services.tip_delivery import bind_destination, dispatch_telegram


SCREENSHOTS = [
    (888, 5, 24970098, 24197597, 772501),
    (893, 18, 14136591, 14066151, 70440),
    (894, 10, 19065831, 19065831, 0),
    (895, 7, 23494169, 23494169, 0),
    (896, 15, 23844478, 23844478, 0),
    (897, 4, 23977479, 23776191, 201288),
    (898, 9, 19361894, 19361894, 0),
    (899, 10, 30410831, 30410831, 0),
]


def round_data(sequence=1, tip=0, **changes):
    return dict(gameId=f'game-{sequence}', sequence=sequence, winningNumber=4,
                totalBets=100, totalPrizes=100-tip, settlementFinal=True,
                totalsComplete=True, **changes)


class ClassifierTests(SimpleTestCase):
    def test_eight_screenshots_reconcile(self):
        statuses = []
        for seq, number, bets, prizes, tip in SCREENSHOTS:
            row = dict(gameId=f'20261027{seq}', sequence=seq, winningNumber=number,
                       totalBets=bets, totalPrizes=prizes, reportedTip=tip,
                       settlementFinal=True, totalsComplete=True)
            result = model.classify_round(row)
            self.assertEqual(result['tipAmount'], tip)
            self.assertAlmostEqual(result['tipPercent'] + result['prizePercent'], 100)
            statuses.append(result['status'])
            if seq == 897:
                self.assertAlmostEqual(result['tipPercent'], 0.8394877543, places=9)
        self.assertEqual(statuses.count('TIP'), 3)

    def test_exact_residual_zero_and_large_amounts(self):
        self.assertEqual(model.classify_round(round_data(tip=1))['status'], 'TIP')
        self.assertEqual(model.classify_round(round_data())['status'], 'NO_TIP')
        result = model.classify_round({**round_data(), 'totalBets': 0, 'totalPrizes': 0})
        self.assertEqual((result['status'], result['tipPercent'], result['prizePercent']), ('NO_TIP', 0, 0))
        result = model.classify_round({**round_data(), 'totalBets': model.MAX_INTEGER, 'totalPrizes': model.MAX_INTEGER-1})
        self.assertEqual((result['status'], result['tipAmount']), ('TIP', 1))

    def test_pending_invalid_and_incomplete_do_not_advance(self):
        state = model.create_state()
        for changes in [
            {'settlementFinal': False}, {'settlementFinal': 1}, {'totalsComplete': False},
            {'totalBets': -1}, {'totalBets': 100.0}, {'totalBets': True}, {'totalBets': '100'},
            {'totalBets': model.MAX_INTEGER+1}, {'totalPrizes': 101}, {'reportedTip': 1},
            {'totalUsers': 5, 'winnerCount': 6}, {'totalUsers': None},
            {'sequence': None}, {'sequence': True}, {'sequence': -1},
            {'winningNumber': 28}, {'gameId': '  '},
        ]:
            with self.subTest(changes=changes):
                updated, result, events = model.advance(state, {**round_data(), **changes})
                self.assertIn(result['status'], ('PENDING', 'INVALID'))
                self.assertEqual(updated, state)
                self.assertEqual(events, [])

    def test_milestones_reset_and_rearm(self):
        state = model.create_state()
        events = []
        for i in range(1, 18):
            state, _, new = model.advance(state, round_data(i))
            events += new
        self.assertEqual([e['threshold'] for e in events], [7, 10, 15])
        self.assertTrue(all('at least' in e['message'] for e in events))
        state, _, new = model.advance(state, round_data(18, tip=1))
        self.assertEqual(new[0]['previousNoTipStreak'], 17)
        self.assertEqual(state['noTipStreak'], 0)
        for i in range(19, 26):
            state, _, new = model.advance(state, round_data(i))
        self.assertEqual(new[0]['threshold'], 7)
        self.assertTrue(new[0]['exactStreak'])
        self.assertEqual(new[0]['lastTipGameId'], 'game-18')
        self.assertNotIn('at least', new[0]['message'])

    def test_duplicates_stale_conflict_and_metadata(self):
        state, _, events = model.advance(model.create_state(), round_data(10, tip=1))
        saved = deepcopy(state)
        for round, expected in [(round_data(10, tip=1), 'DUPLICATE'), (round_data(9), 'STALE'),
                                (round_data(10, tip=2), 'CONFLICT'),
                                (round_data(10, tip=1, totalUsers=10), 'DUPLICATE')]:
            updated, result, new = model.advance(state, round)
            self.assertEqual(result['status'], expected)
            self.assertEqual(updated, saved)
            self.assertEqual(new, [])
        self.assertEqual(state, saved)
        self.assertEqual(model.advance(model.create_state(), round_data(10, tip=1))[2][0]['id'], events[0]['id'])

    def test_gap_clears_exact_streak_and_invalid_round_breaks_later_continuity(self):
        state, _, _ = model.advance(model.create_state(thresholds=[2]), round_data(1, tip=1))
        state, _, _ = model.advance(state, round_data(2))
        state, _, _ = model.advance(state, {**round_data(3), 'reportedTip': 1})
        state, result, events = model.advance(state, round_data(4))
        self.assertTrue(result['gapDetected'])
        self.assertFalse(state['exactStreak'])
        self.assertIsNone(state['lastTipGameId'])
        self.assertEqual(state['noTipStreak'], 1)
        self.assertFalse(events)
        state, _, events = model.advance(state, round_data(5))
        self.assertIn('at least 2', events[0]['message'])

    def test_historical_initialization_suppresses_all_events(self):
        state = model.create_state(thresholds=[1])
        state, _, events = model.advance(state, round_data(1, tip=1), emit_alerts=False)
        self.assertEqual(events, [])
        state, _, events = model.advance(state, round_data(2), emit_alerts=False)
        self.assertEqual(events, [])
        self.assertEqual(state['noTipStreak'], 1)
        self.assertTrue(state['exactStreak'])

    def test_custom_thresholds_validate_sort_and_deduplicate(self):
        state = model.create_state(thresholds=[16, 8, 11, 8])
        self.assertEqual(state['thresholds'], [8, 11, 16])
        events = []
        for i in range(1, 18):
            state, _, new = model.advance(state, round_data(i))
            events += new
        self.assertEqual([e['threshold'] for e in events], [8, 11, 16])
        for thresholds in ([], [0], [True], [1.5], ['7']):
            with self.assertRaises(ValueError):
                model.create_state(thresholds=thresholds)

    def test_date_rollover_is_conservative_and_gaps_survive(self):
        self.assertEqual(tips.source_sequence('202610270898') - tips.source_sequence('20261027897'), 1)
        self.assertGreater(tips.source_sequence('202610280001') - tips.source_sequence('202610271440'), 1)
        self.assertIsNone(tips.source_sequence('202613270001'))
        self.assertIsNone(tips.source_sequence('game-1'))


@override_settings(TIP_MONITOR_ID='lucky28')
class PersistenceTests(TestCase):
    def test_restart_preserves_state_and_failure_is_retryable_in_order(self):
        monitor = tips.TipMonitor()
        first = monitor.ingest(round_data(1, tip=1))['events'][0]
        monitor.ingest(round_data(2, tip=2))
        self.assertEqual(tips.TipMonitor().ingest(round_data(2, tip=2))['result']['status'], 'DUPLICATE')
        failed = Mock(side_effect=RuntimeError('secret-token'))
        self.assertEqual(tips.TipMonitor().dispatch(failed), 0)
        self.assertEqual(failed.call_count, 1)
        self.assertEqual(failed.call_args.args[0]['id'], first['id'])
        self.assertEqual(TipEvent.objects.filter(sent_at__isnull=True).count(), 2)
        self.assertNotIn('secret-token', TipEvent.objects.get(pk=first['id']).last_error)
        sent = Mock()
        self.assertEqual(tips.TipMonitor().dispatch(sent), 2)
        self.assertEqual([call.args[0]['sequence'] for call in sent.call_args_list], [1, 2])
        self.assertEqual(tips.TipMonitor().dispatch(sent), 0)

    def test_false_acknowledgment_is_failure_and_config_mismatch_stops(self):
        monitor = tips.TipMonitor(thresholds=[1])
        monitor.ingest(round_data())
        self.assertEqual(monitor.dispatch(lambda event: False), 0)
        self.assertIsNone(TipEvent.objects.get().sent_at)
        with self.assertRaises(ValueError):
            tips.TipMonitor(thresholds=[7])
        with self.assertRaises(ValueError):
            tips.TipMonitor(thresholds=[])

    def test_dispatch_uses_source_order_even_when_clock_moves_backwards(self):
        monitor = tips.TipMonitor()
        first = monitor.ingest(round_data(1, tip=1))['events'][0]
        second = monitor.ingest(round_data(2, tip=1))['events'][0]
        TipEvent.objects.filter(pk=second['id']).update(created_at=timezone.now()-timedelta(hours=1))
        sent = Mock()
        self.assertEqual(monitor.dispatch(sent), 2)
        self.assertEqual([call.args[0]['id'] for call in sent.call_args_list], [first['id'], second['id']])

    def test_outbox_failure_rolls_back_state_and_evidence(self):
        with patch.object(TipEvent.objects, 'get_or_create', side_effect=RuntimeError('disk full')):
            with self.assertRaises(RuntimeError):
                tips.TipMonitor().ingest(round_data(tip=1))
        self.assertFalse(TipStream.objects.exists())
        self.assertFalse(TipRound.objects.exists())

    def test_source_adapter_does_not_mix_pre_totals_and_winner_totals(self):
        game = GameRound(game_no='202610270897', has_winner=True, status=3, winning_number=4,
                         bet_total_energy=100, win_total_energy=50, winner_raw={'win_total_energy': 50})
        self.assertEqual(model.classify_round(tips.source_round(game))['status'], 'INVALID')
        game.winner_raw = {'bet_total_energy': 100, 'win_total_energy': 99, 'reported_tip': 2}
        self.assertEqual(model.classify_round(tips.source_round(game))['status'], 'INVALID')
        game.winner_raw.update(reported_tip=1, settlement_sequence=1000)
        self.assertEqual(tips.source_round(game)['sequence'], 1000)
        self.assertEqual(model.classify_round(tips.source_round(game))['status'], 'TIP')

    def test_replay_orders_results_without_events_and_refuses_overwrite(self):
        for seq in (3, 1, 2):
            GameRound.objects.create(game_no=f'20261027{seq:04}', winning_number=4, status=3,
                has_winner=True, winner_raw={'bet_total_energy': 100, 'win_total_energy': 99 if seq == 1 else 100})
        before = list(GameRound.objects.values())
        self.assertEqual(tips.initialize_history(), {'TIP': 1, 'NO_TIP': 2})
        state = TipStream.objects.get().state
        self.assertEqual(state['noTipStreak'], 2)
        self.assertTrue(state['exactStreak'])
        self.assertFalse(TipEvent.objects.exists())
        self.assertEqual(before, list(GameRound.objects.values()))
        with self.assertRaises(ValueError):
            tips.initialize_history()

    def test_dashboard_reads_are_side_effect_free_and_monitor_is_validated(self):
        self.assertContains(self.client.get('/tips/'), 'Tip games')
        self.assertEqual(self.client.get('/api/tips/').json()['rounds'], [])
        self.assertFalse(TipStream.objects.exists())
        self.assertEqual(self.client.get('/api/tips/?monitor=../bad').status_code, 400)
        tips.TipMonitor().ingest(round_data(tip=1))
        self.assertEqual(self.client.get('/api/tips/').json()['queued'], 1)

    @patch('games.services.tip_delivery.requests.post')
    @patch('games.services.tip_delivery.get_config')
    def test_telegram_requires_opt_in_ack_and_unchanged_destination(self, config, post):
        config.return_value = Mock(telegram_enabled=False, bot_token='secret')
        monitor = tips.TipMonitor()
        monitor.ingest(round_data(tip=1))
        destination = AlertDestination.objects.create(name='Tips', chat_id='123', enabled=True)
        bind_destination(monitor, destination.pk)
        self.assertEqual(dispatch_telegram('lucky28'), 0)
        post.assert_not_called()
        config.return_value.telegram_enabled = True
        post.return_value.json.return_value = {'ok': False}
        self.assertEqual(dispatch_telegram('lucky28'), 0)
        self.assertIsNone(TipEvent.objects.get().sent_at)
        destination.chat_id = 'changed'
        destination.save()
        post.reset_mock()
        self.assertEqual(dispatch_telegram('lucky28'), 0)
        post.assert_not_called()
        with self.assertRaises(ValueError):
            bind_destination(monitor, destination.pk)
        destination.chat_id = '123'
        destination.save()
        post.return_value.json.return_value = {'ok': True, 'result': {'message_id': 7}}
        self.assertEqual(dispatch_telegram('lucky28'), 1)
        self.assertIsNotNone(TipEvent.objects.get().sent_at)


@override_settings(LOGGER_API_TOKEN='tip-test', TIP_MONITOR_ID='lucky28')
class LoggerIntegrationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.credentials(HTTP_X_LUCKY28_TOKEN='tip-test')

    def winner(self, number=1, observed=None, **changes):
        return self.client.post('/api/logger/events/', {
            'schema_version': 1, 'game_type': 'lucky28', 'game_no': f'20261027{number:04}',
            'phase': 'winner', 'observed_at': (observed or timezone.now()).isoformat(),
            'data': {'winning_number': 4, 'status': 3, **changes},
        }, format='json')

    def test_live_ingestion_queues_once_and_conflicting_totals_are_visible(self):
        response = self.winner(bet_total_energy=100, win_total_energy=99)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(TipEvent.objects.count(), 1)
        self.assertEqual(self.winner(bet_total_energy=100, win_total_energy=99).status_code, 200)
        self.assertEqual(TipEvent.objects.count(), 1)
        self.winner(bet_total_energy=100, win_total_energy=98)
        self.assertEqual(TipRound.objects.get().status, 'CONFLICT')
        self.assertEqual(GameRound.objects.get().win_total_energy, 99)
        self.assertEqual(TipEvent.objects.count(), 1)

    def test_partial_winner_can_complete_without_duplicate_events(self):
        self.winner(win_total_energy=99)
        self.assertEqual(TipRound.objects.get().status, 'INVALID')
        self.assertIsNone(TipStream.objects.get().state['lastSequence'])
        self.winner(bet_total_energy=100, win_total_energy=99)
        self.assertEqual(TipRound.objects.get().status, 'TIP')
        self.assertEqual(GameRound.objects.get().bet_total_energy, 100)
        self.assertEqual(TipEvent.objects.count(), 1)

    def test_historical_ingestion_updates_state_without_alerts(self):
        self.winner(observed=timezone.now()-timedelta(days=1), bet_total_energy=100, win_total_energy=99)
        self.assertEqual(TipRound.objects.get().status, 'TIP')
        self.assertFalse(TipEvent.objects.exists())

    def test_optional_reported_tip_and_completeness_are_preserved(self):
        self.winner(bet_total_energy=100, win_total_energy=99, reported_tip=2)
        self.assertEqual(TipRound.objects.get().status, 'INVALID')
        self.winner(bet_total_energy=100, win_total_energy=99, reported_tip=1, totals_complete=False)
        self.assertEqual(TipRound.objects.get().status, 'INVALID')
        self.winner(bet_total_energy=100, win_total_energy=99, reported_tip=1,
                    totals_complete=True, settlement_sequence=90)
        self.assertEqual(TipRound.objects.get().status, 'TIP')
        self.assertEqual(TipStream.objects.get().state['lastSequence'], 90)
