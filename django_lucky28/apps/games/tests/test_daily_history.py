import csv
import io
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from games.models import GameRound, SignalLog, SignalRule
from games.services.imports import import_history


def timestamp(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def upload(content, name='history.csv'):
    return SimpleUploadedFile(name, content.encode('utf-8'), content_type='text/csv')


@override_settings(TIME_ZONE='UTC')
class DailyHistoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Insert newest first so database ID order differs from event order.
        cls.newest = GameRound.objects.create(
            game_no='day8', winning_number=19, has_winner=True,
            winner_event_ts=timestamp('2026-09-08 00:00:00'),
            winner_count=10, win_total_energy=1000,
        )
        cls.late = GameRound.objects.create(
            game_no='day7-late', winning_number=3, has_winner=True,
            winner_event_ts=timestamp('2026-09-07 23:59:59'),
            winner_count=4, win_total_energy=400,
        )
        cls.early = GameRound.objects.create(
            game_no='day7-early', winning_number=14, has_winner=True,
            winner_event_ts=timestamp('2026-09-07 00:00:00'),
            winner_count=0, win_total_energy=0,
        )
        GameRound.objects.create(
            game_no='old-day', winning_number=0, has_winner=True,
            winner_event_ts=timestamp('2025-12-14 23:59:59'),
        )
        GameRound.objects.create(game_no='undated', winning_number=1, has_winner=True)

    def test_archive_keeps_every_day_and_aggregates_separately(self):
        response = self.client.get('/days/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['saved_days'], 3)
        self.assertEqual(response.context['saved_games'], 4)
        self.assertEqual(response.context['undated_games'], 1)
        days = list(response.context['days'])
        self.assertEqual([str(day['day']) for day in days], ['2026-09-08', '2026-09-07', '2025-12-14'])
        self.assertEqual({key: days[1][key] for key in ['total', 'big', 'small', 'odd', 'even', 'winners', 'prizes']},
                         {'total': 2, 'big': 1, 'small': 1, 'odd': 1, 'even': 1, 'winners': 4, 'prizes': 400})
        self.assertContains(response, '/analysis/?date=2026-09-07')
        self.assertContains(response, '/days/export/?date=2026-09-07')

    def test_dashboard_history_and_analysis_default_to_latest_saved_day(self):
        for path in ['/', '/history/', '/analysis/']:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['selected_date'], '2026-09-08')

    def test_selected_day_uses_result_time_and_excludes_midnight_of_next_day(self):
        for path, key in [('/', 'games'), ('/history/', 'results'), ('/games/dashboard/rows/', 'games')]:
            with self.subTest(path=path):
                response = self.client.get(path, {'date': '2026-09-07'})
                self.assertEqual([game.game_no for game in response.context[key]], ['day7-late', 'day7-early'])
                self.assertEqual(response.context['previous_day'], '2025-12-14')
                self.assertEqual(response.context['next_day'], '2026-09-08')

    def test_empty_day_preserves_selection(self):
        for path in ['/', '/history/', '/analysis/']:
            with self.subTest(path=path):
                response = self.client.get(path, {'date': '2026-08-01'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['selected_date'], '2026-08-01')
        self.assertEqual(response.context['filters']['total_games'], 0)

    def test_invalid_dates_and_ranges_show_errors(self):
        for path in ['/', '/history/', '/analysis/', '/games/dashboard/rows/', '/days/export/']:
            with self.subTest(path=path):
                response = self.client.get(path, {'date': '2026-02-30'})
                self.assertEqual(response.status_code, 400)
        for path in ['/analysis/', '/days/']:
            for params in [
                {'start_date': 'bad'},
                {'start_date': '2026-09-08', 'end_date': '2026-09-07'},
            ]:
                with self.subTest(path=path, params=params):
                    self.assertEqual(self.client.get(path, params).status_code, 400)
        self.assertEqual(self.client.get('/analysis/', {'recent_n': '-1'}).status_code, 400)

    def test_analysis_uses_chronological_order_and_actual_number_frequencies(self):
        response = self.client.get('/analysis/', {'date': '2026-09-07', 'recent_n': 1})
        self.assertEqual(response.context['stats']['total'], 2)
        self.assertEqual(response.context['recent_stats']['small'], 1)
        self.assertEqual(response.context['recent_stats']['odd'], 1)
        self.assertEqual({row['number']: row['count'] for row in response.context['hot_list'] if row['count']},
                         {3: 1, 14: 1})

    def test_inclusive_range_crosses_days_and_keeps_older_history(self):
        params = {'start_date': '2026-09-07', 'end_date': '2026-09-08'}
        self.assertEqual(self.client.get('/analysis/', params).context['stats']['total'], 3)
        archive = self.client.get('/days/', params)
        self.assertEqual(archive.context['saved_days'], 2)
        self.assertEqual(archive.context['saved_games'], 3)
        self.assertEqual(GameRound.objects.count(), 5)

    def test_repetition_windows_follow_timestamps_when_import_order_is_reversed(self):
        start = timestamp('2026-09-06 00:00:00')
        GameRound.objects.bulk_create([
            GameRound(game_no=f'reversed-{i}', winning_number=i, has_winner=True,
                      winner_event_ts=start + timedelta(minutes=i))
            for i in reversed(range(12))
        ])
        response = self.client.get('/analysis/', {'date': '2026-09-06'})
        windows = response.context['repetition_rows']
        self.assertEqual(windows[0]['numbers'], list(range(2, 12)))
        self.assertEqual(windows[0]['start_game'], 'reversed-2')
        self.assertEqual(windows[0]['end_game'], 'reversed-11')

    def test_all_day_records_remain_accessible_and_analysis_is_not_capped(self):
        start = timestamp('2026-09-06 00:00:00')
        GameRound.objects.bulk_create([
            GameRound(game_no=f'full-day-{i}', winning_number=i % 28, has_winner=True,
                      winner_event_ts=start + timedelta(seconds=i))
            for i in range(2005)
        ])
        response = self.client.get('/', {'date': '2026-09-06', 'page': 2})
        self.assertEqual(len(response.context['games']), 50)
        self.assertEqual(response.context['page_obj'].paginator.count, 2005)
        partial = self.client.get('/games/dashboard/rows/', {'date': '2026-09-06', 'page': 2})
        self.assertEqual([game.pk for game in partial.context['games']], [game.pk for game in response.context['games']])
        history = self.client.get('/history/', {'date': '2026-09-06', 'page': 21})
        self.assertEqual(len(history.context['results']), 5)
        analysis = self.client.get('/analysis/', {'date': '2026-09-06'})
        self.assertEqual(analysis.context['stats']['total'], 2005)
        windows = analysis.context['repetition_rows']
        self.assertEqual(len(windows), 50)
        self.assertEqual(windows[0]['end_game'], 'full-day-2004')
        export = self.client.get('/days/export/', {'date': '2026-09-06'})
        self.assertEqual(len(list(csv.DictReader(io.StringIO(export.content.decode())))), 2005)

    def test_export_preserves_zeros_ids_and_date(self):
        response = self.client.get('/days/export/', {'date': '2026-09-07'})
        self.assertIn('lucky28-2026-09-07.csv', response['Content-Disposition'])
        rows = list(csv.DictReader(io.StringIO(response.content.decode())))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1], {
            'result': '14', 'timestamp': '2026-09-07 00:00:00',
            'winners_count': '0', 'prize_amount': '0', 'game_no': 'day7-early',
        })
        summary = import_history([upload(response.content.decode())])
        self.assertEqual(summary['created'], 0)
        self.assertEqual(GameRound.objects.count(), 5)

    def test_export_preserves_fractional_seconds_for_reimport(self):
        self.newest.winner_event_ts = timestamp('2026-09-08 00:00:00.123456')
        self.newest.save()
        response = self.client.get('/days/export/', {'date': '2026-09-08'})
        self.assertIn('2026-09-08 00:00:00.123456', response.content.decode())
        self.assertEqual(import_history([upload(response.content.decode())])['created'], 0)


@override_settings(TIME_ZONE='UTC')
class DayDeletionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first = GameRound.objects.create(
            game_no='delete-first', winning_number=14, has_winner=True,
            winner_event_ts=timestamp('2026-09-07 00:00:00'),
        )
        cls.last = GameRound.objects.create(
            game_no='delete-last', winning_number=3, has_winner=True,
            winner_event_ts=timestamp('2026-09-07 23:59:59.999999'),
        )
        cls.other = GameRound.objects.create(
            game_no='keep-next-day', winning_number=19, has_winner=True,
            winner_event_ts=timestamp('2026-09-08 00:00:00'),
        )
        GameRound.objects.create(game_no='keep-undated', winning_number=1, has_winner=True)
        GameRound.objects.create(
            game_no='keep-pending', has_pre=True,
            pre_event_ts=timestamp('2026-09-07 12:00:00'),
        )
        cls.rule = SignalRule.objects.create(
            name='Test rule', rule_type='STREAK', dimension='BIG_SMALL',
            target_value='Big', threshold=1,
        )
        SignalLog.objects.create(game=cls.first, rule=cls.rule, value=1)
        SignalLog.objects.create(game=cls.other, rule=cls.rule, value=1)

    def test_archive_links_to_confirmation_and_get_preserves_data(self):
        self.assertContains(self.client.get('/days/'), '/days/delete/?date=2026-09-07')
        response = self.client.get('/days/delete/', {'date': '2026-09-07'})
        self.assertContains(response, '2 saved results')
        self.assertContains(response, '2026-09-07')
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.assertEqual(response.context['result_count'], 2)
        self.assertEqual(GameRound.objects.count(), 5)
        self.assertEqual(SignalLog.objects.count(), 2)

    def test_confirmed_delete_removes_the_entire_day_and_related_signals(self):
        GameRound.objects.bulk_create([
            GameRound(game_no=f'delete-extra-{i}', winning_number=2, has_winner=True,
                      winner_event_ts=timestamp('2026-09-07 12:00:00') + timedelta(seconds=i))
            for i in range(60)
        ])
        response = self.client.post('/days/delete/', {'date': '2026-09-07', 'confirm': 'true'}, follow=True)
        self.assertContains(response, 'Deleted 62 saved results for 2026-09-07 (UTC).')
        self.assertEqual(set(GameRound.objects.values_list('game_no', flat=True)),
                         {'keep-next-day', 'keep-undated', 'keep-pending'})
        self.assertEqual(list(SignalLog.objects.values_list('game_id', flat=True)), [self.other.pk])
        self.assertTrue(SignalRule.objects.filter(pk=self.rule.pk).exists())
        self.assertEqual(response.context['saved_days'], 1)
        self.assertEqual(response.context['saved_games'], 1)
        self.assertTrue(self.client.get('/analysis/', {'date': '2026-09-07'}).context['no_data'])

    def test_missing_or_invalid_date_never_falls_back_to_deleting_latest_day(self):
        for params in [{'confirm': 'true'}, {'date': '', 'confirm': 'true'},
                       {'date': '2026-02-30', 'confirm': 'true'}]:
            for method in [self.client.get, self.client.post]:
                with self.subTest(params=params, method=method.__name__):
                    self.assertEqual(method('/days/delete/', params).status_code, 400)
                    self.assertEqual(GameRound.objects.count(), 5)

    def test_post_requires_explicit_confirmation(self):
        for params in [{'date': '2026-09-07'}, {'date': '2026-09-07', 'confirm': 'false'}]:
            with self.subTest(params=params):
                response = self.client.post('/days/delete/', params)
                self.assertContains(response, 'Confirm deletion', status_code=400)
                self.assertEqual(GameRound.objects.count(), 5)

    def test_csrf_is_required_and_confirmation_form_token_works(self):
        client = Client(enforce_csrf_checks=True)
        params = {'date': '2026-09-07', 'confirm': 'true'}
        self.assertEqual(client.post('/days/delete/', params).status_code, 403)
        self.assertEqual(GameRound.objects.count(), 5)
        client.get('/days/delete/', {'date': '2026-09-07'})
        params['csrfmiddlewaretoken'] = client.cookies['csrftoken'].value
        self.assertEqual(client.post('/days/delete/', params).status_code, 302)
        self.assertEqual(GameRound.objects.count(), 3)

    def test_repeated_or_empty_day_delete_leaves_other_days_unchanged(self):
        params = {'date': '2026-09-07', 'confirm': 'true'}
        self.client.post('/days/delete/', params)
        response = self.client.post('/days/delete/', params, follow=True)
        self.assertContains(response, 'No saved results remain for 2026-09-07')
        self.assertEqual(GameRound.objects.count(), 3)
        confirmation = self.client.get('/days/delete/', {'date': '2026-09-07'})
        self.assertNotContains(confirmation, 'name="confirm"')

    def test_deleting_latest_day_selects_next_available_day(self):
        self.client.post('/days/delete/', {'date': '2026-09-08', 'confirm': 'true'})
        self.assertEqual(self.client.get('/').context['selected_date'], '2026-09-07')

    def test_unsupported_methods_cannot_delete(self):
        self.assertEqual(self.client.delete('/days/delete/?date=2026-09-07').status_code, 405)
        self.assertEqual(GameRound.objects.count(), 5)


@override_settings(TIME_ZONE='UTC')
class HistoryImportTests(TestCase):
    header = 'result,timestamp,winners_count,prize_amount\n'

    @patch('games.services.signals.SignalAnalyzer.analyze_game')
    def test_multiple_files_append_days_and_reimports_are_idempotent(self, analyze):
        old = GameRound.objects.create(
            game_no='saved-old', winning_number=2, has_winner=True,
            winner_event_ts=timestamp('2025-12-14 12:00:00'),
        )
        contents = [self.header + '19,2026-09-08 00:00:00,10,1000\n',
                    self.header + '14,2026-09-07 23:59:00,0,0\n']
        for attempt in range(2):
            response = self.client.post('/games/import/', {'csv_file': [upload(content, f'day-{i}.csv') for i, content in enumerate(contents)]}, follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(GameRound.objects.count(), 3)
            self.assertTrue(GameRound.objects.filter(pk=old.pk).exists())
        self.assertContains(response, 'already saved 2')
        analyze.assert_not_called()

    def test_same_minute_distinct_results_survive_and_exact_duplicates_do_not_repeat(self):
        content = self.header + ('19,2026-09-07 13:00:00,10,1000\n'
                                 '14,2026-09-07 13:00:30,11,1100\n'
                                 '14,2026-09-07 13:00:30,11,1100\n')
        summary = import_history([upload(content)])
        self.assertEqual(summary['created'], 2)
        self.assertEqual(summary['unchanged'], 1)
        self.assertEqual(import_history([upload(content)])['created'], 0)

    def test_conflicting_result_at_same_timestamp_requires_an_explicit_game_id(self):
        import_history([upload(self.header + '19,2026-09-07 13:00:00,10,1000\n')])
        with self.assertRaisesMessage(ValueError, 'A different result is already saved'):
            import_history([upload(self.header + '14,2026-09-07 13:00:00,11,1100\n')])
        self.assertEqual(GameRound.objects.count(), 1)
        content = 'result,timestamp,game_no\n14,2026-09-07 13:00:00,separate-game\n'
        self.assertEqual(import_history([upload(content)])['created'], 1)

    def test_existing_minute_id_is_recognized_and_missing_metadata_is_filled(self):
        game = GameRound.objects.create(
            game_no='202609071300', winning_number=19, has_winner=True,
            winner_event_ts=timestamp('2026-09-07 13:00:00'),
        )
        summary = import_history([upload(self.header + '19,2026-09-07 13:00:00,0,0\n')])
        game.refresh_from_db()
        self.assertEqual(summary['updated'], 1)
        self.assertEqual((game.winner_count, game.win_total_energy), (0, 0))
        self.assertEqual(GameRound.objects.count(), 1)

    def test_invalid_rows_roll_back_the_entire_upload(self):
        good = self.header + '19,2026-09-07 13:00:00,10,1000\n'
        for bad in [
            self.header + '14,,0,0\n',
            self.header + '28,2026-09-07 13:01:00,0,0\n',
            self.header + '14,2026-09-07 13:01:00,-1,0\n',
            'result,game_no\n14,missing-date\n',
        ]:
            with self.subTest(bad=bad):
                response = self.client.post('/games/import/', {'csv_file': [upload(good), upload(bad, 'bad.csv')]}, follow=True)
                self.assertContains(response, 'Import cancelled; no changes saved.')
                self.assertEqual(GameRound.objects.count(), 0)

    def test_conflicting_id_cannot_overwrite_another_day(self):
        game = GameRound.objects.create(
            game_no='same-id', winning_number=14, has_winner=True,
            winner_event_ts=timestamp('2026-09-07 13:00:00'),
        )
        content = 'result,timestamp,game_no\n19,2026-09-08 13:00:00,same-id\n'
        with self.assertRaisesMessage(ValueError, 'conflicts with a saved result'):
            import_history([upload(content)])
        game.refresh_from_db()
        self.assertEqual(game.winner_event_ts, timestamp('2026-09-07 13:00:00'))
        self.assertEqual(game.winning_number, 14)

    def test_offset_timestamp_is_assigned_to_its_utc_day(self):
        import_history([upload(self.header + '19,2026-09-08T01:00:00+05:30,0,0\n')])
        response = self.client.get('/days/')
        self.assertEqual(str(list(response.context['days'])[0]['day']), '2026-09-07')
