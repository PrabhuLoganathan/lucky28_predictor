from datetime import timedelta
import json
from pathlib import Path
import tempfile

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from games.models import GameRound, AlertDelivery
from games.services import case_study as service
from games.services import case_study_analysis as analysis


def history(numbers, start=1):
    return [dict(round_id=f'20261024{i:04}', number=n, observed_at=f'2026-10-24T10:{i:02}:00+00:00')
            for i, n in enumerate(numbers, start)]


class AnalysisTests(SimpleTestCase):
    def test_normalized_models_and_deterministic_ties(self):
        value = analysis.forecast(history([0, 0, 13, 14]))
        for model in value['strategies']:
            self.assertAlmostEqual(sum(model['probabilities']), 1)
            self.assertEqual(set(model['ranked_numbers']), set(range(28)))
            self.assertTrue(all(p > 0 for p in model['probabilities']))
        self.assertEqual(value['strategies'][0]['ranked_numbers'][:2], [13, 14])
        self.assertEqual(value['strategies'][0]['probabilities'][0], .001)
        self.assertEqual(analysis.forecast([])['history_quality']['status'], 'empty')

    def test_zero_repeat_and_target_is_excluded(self):
        earlier = history([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
        target = dict(round_id='202610240011', number=0, digits=[0, 0, 0])
        detail = analysis.explain(target, earlier+[target])
        self.assertEqual(detail['classification']['kind'], 'repeated')
        self.assertEqual(detail['number_gap']['observed_games'], 9)
        self.assertEqual(detail['groups']['parity'], 'E')
        self.assertEqual(detail['calculation']['status'], 'verified')
        self.assertEqual(detail['evidence_mode'], 'retrospective')

    def test_missing_target_boundary_and_day_change_are_unknown(self):
        earlier = history(range(10))
        for identity in ('202610240012', '202610250001'):
            detail = analysis.explain(dict(round_id=identity, number=1), earlier)
            self.assertEqual(detail['classification']['kind'], 'unknown')
            self.assertTrue(detail['number_gap']['interrupted'])

    def test_new_and_streaks_with_misses(self):
        earlier = history([2]*10)
        result = dict(round_id='202610240011', number=17, digits=[4, 4, 9])
        detail = analysis.explain(result, earlier, analysis.forecast(earlier), evidence_mode='retrospective')
        self.assertEqual(detail['classification']['kind'], 'new')
        self.assertEqual(detail['evidence_mode'], 'retrospective')
        self.assertTrue(any(r['group'] == 'E' and r['count'] == 10 for r in detail['broken_streaks']))
        self.assertFalse(detail['strategy_results'][0]['top']['1']['hit'])
        self.assertEqual(detail['calculation']['status'], 'verified')
        self.assertEqual(analysis.calculation(dict(number=10, digits=[4, 4, 9]))['status'], 'mismatch')
        self.assertEqual(analysis.calculation(dict(number=1, digits=[True, 0, 0]))['status'], 'invalid')
        self.assertEqual(analysis.calculation(dict(number=1))['status'], 'unavailable')


class JournalTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(CASE_STUDY_DB_PATH=Path(self.directory.name)/'study.sqlite3')
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.now = timezone.now()
        for i in range(1, 12):
            GameRound.objects.create(game_no=f'20261024{i:04}', game_type='lucky28', winning_number=i,
                has_winner=True, status=3, winner_event_ts=self.now-timedelta(minutes=12-i))

    def pending(self):
        return GameRound.objects.create(game_no='202610240012', game_type='lucky28', has_pre=True,
                                        pre_event_ts=timezone.now(), status=2)

    def settle(self, game, number=13, observed=None):
        game.has_winner=True
        game.winning_number=number
        game.status=3
        game.winner_event_ts=observed or timezone.now()+timedelta(seconds=2)
        game.save()

    def test_read_requests_do_not_create_journal(self):
        self.assertEqual(self.client.get('/api/case-study/').status_code, 200)
        self.assertFalse(service.journal_path().exists())
        self.assertEqual(self.client.get('/api/case-study/999/').status_code, 404)
        self.assertEqual(self.client.get('/api/case-study/?stream=../bad').status_code, 400)

    def test_backfill_is_retrospective_idempotent_and_source_read_only(self):
        before=list(GameRound.objects.values())
        service.synchronize()
        service.synchronize()
        result=service.dashboard()
        self.assertEqual(result['totals']['retrospective'], 11)
        self.assertNotIn('prospective', result['totals'])
        self.assertEqual(before,list(GameRound.objects.values()))
        self.assertEqual(AlertDelivery.objects.count(),0)
        self.assertEqual(len(list(service.export_records())),11)
        self.assertEqual(result['performance'][0]['samples'],11)

    def test_live_prediction_is_frozen_then_scored(self):
        game=self.pending()
        service.synchronize()
        pending=service.dashboard()['pending'][0]
        self.assertEqual(pending['history_count'],11)
        original=json.dumps(pending)
        self.settle(game)
        service.synchronize()
        case=service.case_detail(service.dashboard()['cases'][0]['id'])
        self.assertEqual(case['mode'],'prospective')
        self.assertEqual(json.dumps(case['forecast']),original)
        self.assertEqual(case['explanation']['strategy_results'][0]['top']['1']['hit'],True)
        records=list(service.export_records())
        self.assertEqual(sum(e['kind']=='forecast_locked' for e in records),1)
        self.assertEqual(service.dashboard()['pending'],[])
        scores=[x for x in service.dashboard()['performance'] if x['mode']=='prospective']
        self.assertEqual(len(scores),9)
        self.assertTrue(all(x['samples']==1 for x in scores))

    def test_late_result_is_never_scored_prospectively(self):
        game=self.pending()
        service.synchronize()
        self.settle(game, observed=self.now-timedelta(seconds=1))
        service.synchronize()
        case=next(c for c in service.dashboard()['cases'] if c['round_id']==game.game_no)
        self.assertEqual(case['mode'],'late')
        self.assertFalse(any(r['mode']=='prospective' for r in service.dashboard()['performance']))

    def test_corrections_append_revision_and_replace_scored_outcome(self):
        game=self.pending();service.synchronize();self.settle(game);service.synchronize()
        original=service.dashboard()['cases'][0]['id']
        game.winning_number=0;game.save();service.synchronize()
        newest=service.dashboard()['cases'][0]
        self.assertEqual(newest['revision'],2)
        self.assertEqual(service.case_detail(original)['result']['number'],13)
        self.assertEqual(service.case_detail(newest['id'])['result']['number'],0)
        baseline=next(r for r in service.dashboard()['performance'] if r['mode']=='prospective' and r['strategy']=='theoretical' and r['top_k']==1)
        self.assertEqual((baseline['samples'],baseline['hits']),(1,0))
        response=self.client.get('/case-study/export/')
        exported=[json.loads(line) for line in b''.join(response.streaming_content).splitlines()]
        self.assertTrue(any(r['kind']=='result_revision' for r in exported))

    def test_stale_pre_and_synthetic_ids_do_not_generate_forecasts(self):
        game=self.pending();game.pre_event_ts=self.now-timedelta(minutes=5);game.save()
        GameRound.objects.create(game_no='TEST_1',has_pre=True,pre_event_ts=timezone.now())
        service.synchronize()
        self.assertEqual(service.dashboard()['pending'],[])

    def test_fresh_packet_for_an_older_round_is_not_an_upcoming_forecast(self):
        GameRound.objects.create(game_no='202610230999',game_type='lucky28',has_pre=True,pre_event_ts=timezone.now())
        service.synchronize()
        self.assertEqual(service.dashboard()['pending'],[])

    def test_historical_correction_revises_dependent_review_without_erasing_original(self):
        service.synchronize()
        first=service.dashboard()['cases'][0]
        original=service.case_detail(first['id'])
        game=GameRound.objects.get(game_no='202610240001')
        game.winning_number=0;game.save()
        service.synchronize()
        revised=service.dashboard()['cases'][0]
        self.assertEqual(revised['round_id'],first['round_id'])
        self.assertEqual(revised['revision'],2)
        original.pop('events')
        preserved=service.case_detail(first['id']);events=preserved.pop('events')
        self.assertEqual(preserved,original)
        self.assertTrue(any(event['kind']=='result_revision' for event in events))
        self.assertEqual(service.case_detail(revised['id'])['history'][0]['number'],0)
