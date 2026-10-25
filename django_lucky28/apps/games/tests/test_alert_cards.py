from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from django.test import TestCase, SimpleTestCase
from django.utils import timezone
from PIL import Image

from games.models import GameRound
from games.services.card_timeline import snapshot_for_round
from games.services.alert_card import card_model, style_key
from games.services.alert_presentation import format_message, render_card
from games.services.timeline import build_timeline


class CardTimelineTests(TestCase):
    def setUp(self):
        self.base = timezone.now() - timedelta(hours=3)
        GameRound.objects.bulk_create([GameRound(game_no=f'R{i}', game_type='lucky28',
            winning_number=i%28, has_winner=True, status=3, winner_event_ts=self.base+timedelta(minutes=i)) for i in range(160)])

    def test_snapshot_matches_global_timeline_and_does_not_include_future_games(self):
        snapshot = snapshot_for_round('lucky28', 'R155')
        self.assertEqual(len(snapshot['games']), 150)
        self.assertEqual(snapshot['games'][0]['game_no'], 'R155')
        self.assertEqual(snapshot['games'][-1]['game_no'], 'R6')
        self.assertEqual(snapshot['tracks']['window']['letters'][-1], '?')
        live = build_timeline('lucky28', ['color', 'row', 'window'])
        latest = snapshot_for_round('lucky28', 'R159')
        for track in live['tracks']:
            self.assertEqual(latest['tracks'][track['tracker_key']]['letters'], [i['letter'] for i in track['timeline']])

    def test_frozen_card_render_never_reads_database(self):
        payload = dict(game_no='R159', matches=[], global_timeline=snapshot_for_round('lucky28', 'R159'))
        original = render_card(payload)
        GameRound.objects.filter(game_no='R159').update(winning_number=0)
        with self.assertNumQueries(0):
            self.assertEqual(render_card(payload), original)
        self.assertEqual(payload['global_timeline']['games'][0]['number'], 19)

    def test_stream_isolation_and_invalid_results(self):
        GameRound.objects.create(game_no='OTHER', game_type='other', winning_number=9,
            has_winner=True, status=3, winner_event_ts=self.base)
        self.assertEqual(snapshot_for_round('other', 'R159')['games'], [])
        GameRound.objects.filter(game_no='R158').update(status=2)
        snapshot = snapshot_for_round('lucky28', 'R159')
        self.assertTrue(snapshot['games'][0]['gap_before'])
        self.assertEqual(snapshot['tracks']['window']['letters'][0], '?')


class CardDesignTests(SimpleTestCase):
    def test_group_families_have_matching_clear_card_and_caption_identities(self):
        samples = [('R03', 'ROW', 'R3', 'row'), ('C02', 'COLUMN', 'C2', 'column'),
                   ('SE', 'COMBINATION', 'SE', 'combination'), ('G04', 'COLOR', 'G04', 'color_group')]
        accents = set()
        for group_id, family, badge, icon in samples:
            with self.subTest(group_id=group_id):
                payload = dict(group_id=group_id, group_name='Old generic name', mode='absence',
                    change_type='ended', count=10, lower_bound=False, threshold=5,
                    ended_number=6, evaluated_round='R12', ended_at='now', stream='lucky28',
                    numbers=[6], details_path='/detail/R12/', matches=[])
                kind = 'group_end' if family == 'COLOR' else 'category_end'
                model = card_model(payload, kind)
                self.assertEqual(model['label'], f'{family} ABSENCE ENDED')
                self.assertEqual(model['identity']['badge'], badge)
                self.assertEqual(model['identity']['icon'], icon)
                self.assertIn(f'<b>{family} ABSENCE ENDED</b>', format_message(payload, kind))
                self.assertIn('Returned: 6', model['return_detail'])
                accents.add(model['accent'])
                payload['mode'] = 'streak'
                self.assertEqual(card_model(payload, kind)['label'], f'{family} STREAK ENDED')
                self.assertEqual(card_model(payload, kind)['return_detail'], '')
        self.assertEqual(len(accents), 4)

    def test_unknown_group_retains_generic_fallback(self):
        payload = dict(group_id='future', mode='absence', change_type='ended', count=2, matches=[])
        model = card_model(payload, 'category_end')
        self.assertEqual(model['label'], 'ABSENCE ENDED')
        self.assertIsNone(model['identity'])

    def test_group_membership_symbols_and_ending_sticker(self):
        payload = dict(game_no='R3', group_id='R03', group_name='Row 3', mode='streak', count=2,
            timeline=[dict(number=21),dict(number=14),dict(number=20)], change_type='ended', matches=[])
        model = card_model(payload, 'category_end')
        self.assertEqual(model['focus']['letters'], ['M','H','H'])
        self.assertEqual(style_key(payload, 'category_end'), 'ended')
        self.assertEqual(model['count'], '2')

    def test_all_kinds_render_with_legacy_payloads_and_long_names(self):
        payload = dict(game_no='R3', captured_at=timezone.now().isoformat(),
            group_id='G01', color='Red', numbers=[0,1,26,27], absence=12345, threshold=100,
            count=12345, group_name='A'*500, mode='absence', lower_bound=True, kind='repeat',
            result=dict(number=9), timeline=[dict(number=i%28) for i in range(150)],
            matches=[dict(title='A'*2000, detail='details '*200, group='color', mode='absence')]*20)
        for kind in ('alert','group','category','category_end','window','result','health'):
            with self.subTest(kind=kind):
                result = render_card(payload, kind)
                self.assertLess(len(result), 400000)
                image = Image.open(BytesIO(result))
                self.assertEqual(image.width, 1080)
                self.assertLess(image.height, 1900)

    def test_caption_limit_handles_unicode_and_html_without_broken_tags(self):
        payload = dict(game_no='R1', captured_at='now', stream='😀'*800, lower_bound=False,
            color='Red', group_id='G01', numbers=[0,1,26,27], absence=12, threshold=10,
            last_number=0, last_round='R0', last_timestamp='earlier', evaluated_round='R1',
            details_path='/detail', global_timeline={'games':[dict(number=0)]})
        text = format_message(payload, 'group', limit=1024)
        self.assertLessEqual(len(text.encode('utf-16-le'))//2, 1024)
        self.assertTrue(text.startswith('⌛'))
        self.assertIn('Timeline snapshot', text)
        self.assertEqual(text.count('<b>'),text.count('</b>'))

    def test_render_deadline_preserved(self):
        with self.assertRaises(TimeoutError):
            render_card(dict(game_no='R1', matches=[]), budget=0)
