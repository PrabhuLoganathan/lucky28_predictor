from copy import deepcopy
from datetime import timedelta
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import requests
from django.test import TestCase, SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from games.models import AlertRule, AlertDestination, AlertDelivery, GameRound
from games.services.alert_album import (render_album, format_album_caption, Page,
                                       timeline_page, capture_time, round_id)
from games.services.alert_card import card_model
from games.services.alert_delivery import deliver_one
from games.services.alerts import record_live_event


def payload():
    return dict(game_no='202610290864', captured_at='2026-10-29T07:21:43+00:00',
        matches=[dict(title='Yellow drought', detail='No Yellow in the last 1 completed round.',
            group='color', mode='absence', values=['Yellow'], observed=1, threshold=1)],
        global_timeline=dict(games=[dict(number=i%28, game_no=f'R{150-i}',
            new_repeat=dict(kind='new', run=1), tip=dict(status='TIP' if i%3 == 0 else 'NO_TIP'),
            gap_before=i == 40) for i in range(150)]))


class AlbumRenderTests(SimpleTestCase):
    def test_three_square_images_from_one_unchanged_snapshot(self):
        evidence = payload()
        before = deepcopy(evidence)
        text_calls = []
        original = Page.text
        def record(page, x, y, value, *args, **kwargs):
            text_calls.append(str(value))
            return original(page, x, y, value, *args, **kwargs)
        with patch.object(Page, 'text', record):
            pages = render_album(evidence)
        self.assertEqual(len(pages), 3)
        for content in pages:
            self.assertEqual(Image.open(BytesIO(content)).size, (1600, 1600))
            self.assertLess(len(content), 1_500_000)
        self.assertEqual(text_calls.count('ROUND #202610290864'), 3)
        self.assertEqual(text_calls.count('CAPTURED  29 Oct 2026 · 12:51:43 PM IST'), 3)
        self.assertEqual(evidence, before)
        self.assertEqual(render_album(evidence), pages)

    def test_timeline_keeps_all_150_entries_in_saved_order(self):
        evidence = payload()
        model = card_model(evidence, 'alert')
        letters = []
        original = Page.text
        def record(page, x, y, value, size=28, *args, **kwargs):
            if size == 26 and kwargs.get('anchor') == 'ma':
                letters.append(str(value))
            return original(page, x, y, value, size, *args, **kwargs)
        with patch.object(Page, 'text', record):
            timeline_page(evidence, 'alert', model, lambda: None)
        self.assertEqual(letters, model['focus']['letters'])
        self.assertEqual(len(letters), 150)

    def test_short_caption_contains_condition_members_round_and_ist_time(self):
        caption = format_album_caption(payload(), 'alert')
        self.assertIn('🟡 <b>YELLOW GROUP — ABSENCE</b>', caption)
        self.assertIn('Absent for: 1 completed round', caption)
        self.assertIn('Numbers: 2, 3, 24, 25', caption)
        self.assertIn('Round: 202610290864', caption)
        self.assertIn('Updated: 29 Oct · 12:51 PM IST', caption)
        self.assertNotIn('Timeline snapshot', caption)
        self.assertLess(len(caption), 400)

    def test_missing_legacy_timeline_is_explicit_and_deadline_is_bounded(self):
        evidence = dict(game_no='old', matches=[], captured_at='not saved')
        self.assertEqual(len(render_album(evidence)), 3)
        self.assertEqual(capture_time(evidence), 'not saved')
        self.assertEqual(round_id({'evaluated_round': 'R2'}), 'R2')
        with self.assertRaises(TimeoutError):
            render_album(evidence, budget=0)

    def test_caption_escapes_html_and_stays_within_unicode_budget(self):
        evidence = payload()
        evidence['game_no'] = '<&😀>' * 200
        evidence['captured_at'] = '<&😀>' * 200
        evidence['matches'] = [dict(title='<&😀>'*200, detail='<&😀>'*300, group='number', mode='density')]
        caption = format_album_caption(evidence, 'alert')
        self.assertLessEqual(len(caption.encode('utf-16-le'))//2, 1024)
        self.assertNotIn('<&', caption)
        self.assertEqual(caption.count('<b>'), caption.count('</b>'))


@override_settings(ALERT_TELEGRAM_ENABLED=True, ALERT_TELEGRAM_BOT_TOKEN='test-token')
class AlbumDeliveryTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        settings = override_settings(ALERT_STATE_DIR=Path(self.directory.name))
        settings.enable()
        self.addCleanup(settings.disable)
        AlertRule.objects.create(key='album', title='New round', series='number', mode='every_game')
        self.destination = AlertDestination.objects.create(name='Album channel', chat_id='123', enabled=True)
        game = GameRound.objects.create(game_no='album-round', game_type='lucky28', has_pre=True,
            pre_event_ts=timezone.now())
        record_live_event(game, 'pre')
        self.delivery = AlertDelivery.objects.get(kind='alert')
        self.local = dict(REMOTE_ADDR='127.0.0.1', HTTP_HOST='localhost')

    def response(self, ids=(101, 102, 103)):
        return Mock(status_code=200, json=lambda: dict(ok=True,
            result=[dict(message_id=i, media_group_id='album-1') for i in ids]))

    @patch('games.services.alert_delivery.requests.post')
    def test_album_upload_archive_and_all_message_ids(self, post):
        post.return_value = self.response()
        self.assertTrue(deliver_one(self.delivery.pk))
        self.assertFalse(deliver_one(self.delivery.pk))
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, 'sent')
        self.assertEqual(self.delivery.message_id, 101)
        self.assertEqual(self.delivery.message_ids, [101, 102, 103])
        self.assertEqual(self.delivery.media_group_id, 'album-1')
        self.assertTrue(post.call_args.args[0].endswith('/sendMediaGroup'))
        data = post.call_args.kwargs['data']
        media = json.loads(data['media'])
        self.assertEqual(len(media), 3)
        self.assertIn('caption', media[0])
        self.assertNotIn('caption', media[1])
        self.assertNotIn('caption', media[2])
        self.assertEqual(media[0]['parse_mode'], 'HTML')
        files = post.call_args.kwargs['files']
        self.assertEqual(set(files), {'photo1', 'photo2', 'photo3'})
        archive = json.loads(Path(self.delivery.artifact_path).read_text())
        self.assertEqual(archive['data'], data)
        self.assertEqual(archive['image_count'], 3)
        for index, item in enumerate(media, 1):
            self.assertEqual(item['media'], f'attach://photo{index}')
            content = files[f'photo{index}'][1]
            suffix = '' if index == 1 else f'-{index}'
            self.assertEqual(Path(self.directory.name, 'artifacts', f'{self.delivery.pk}{suffix}.jpg').read_bytes(), content)
            self.assertEqual(Image.open(BytesIO(content)).size, (1600,1600))
        page = self.client.get(reverse('alert_delivery_detail', args=[self.delivery.pk]), **self.local)
        self.assertContains(page, 'Verification timeline')
        self.assertContains(page, '101, 102, 103')
        for index in (1,2,3):
            image = self.client.get(reverse('alert_delivery_image', args=[self.delivery.pk])+f'?page={index}', **self.local)
            self.assertEqual(image.status_code, 200)
            image.close()
        self.assertEqual(self.client.get(reverse('alert_delivery_image', args=[self.delivery.pk])+'?page=../../secret', **self.local).status_code, 404)

    @patch('games.services.alert_delivery.requests.post')
    def test_incomplete_or_malformed_success_is_uncertain_and_not_retried(self, post):
        for result in ([dict(message_id=1, media_group_id='a')],
                       [dict(message_id=i, media_group_id=str(i)) for i in range(3)],
                       [dict(message_id=1, media_group_id='a')]*3,
                       [dict(message_id=i) for i in range(3)],
                       [dict(message_id=i, media_group_id='a') for i in range(3)] + [None],
                       dict(message_id=1)):
            with self.subTest(result=result):
                AlertDelivery.objects.filter(pk=self.delivery.pk).update(status='pending')
                post.reset_mock()
                post.return_value = Mock(status_code=200, json=lambda: dict(ok=True, result=result))
                deliver_one(self.delivery.pk)
                self.delivery.refresh_from_db()
                self.assertEqual(self.delivery.status, 'uncertain')
                self.assertFalse(deliver_one(self.delivery.pk))
                post.assert_called_once()

    @patch('games.services.alert_delivery.requests.post', side_effect=requests.Timeout())
    def test_timeout_never_falls_back_to_another_send(self, post):
        deliver_one(self.delivery.pk)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, 'uncertain')
        self.assertFalse(deliver_one(self.delivery.pk))
        post.assert_called_once()

    @patch('games.services.alert_delivery.requests.post')
    def test_rate_limit_retries_one_album_and_renderer_failure_uses_text(self, post):
        post.return_value = Mock(status_code=429, json=lambda: dict(ok=False, parameters=dict(retry_after=1)))
        deliver_one(self.delivery.pk)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, 'pending')
        AlertDelivery.objects.filter(pk=self.delivery.pk).update(available_at=timezone.now()-timedelta(seconds=1))
        post.return_value = self.response()
        deliver_one(self.delivery.pk)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, 'sent')
        AlertDelivery.objects.filter(pk=self.delivery.pk).update(status='pending')
        post.return_value = Mock(status_code=200, json=lambda: dict(ok=True, result=dict(message_id=104)))
        with patch('games.services.alert_delivery.render_album', side_effect=RuntimeError('render failed')):
            deliver_one(self.delivery.pk)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, 'sent')
        self.assertTrue(post.call_args.args[0].endswith('/sendMessage'))
        self.assertIsNone(post.call_args.kwargs['files'])
        self.assertEqual(json.loads(Path(self.delivery.artifact_path).read_text())['image_count'], 0)

    @patch('games.services.alert_delivery.requests.post')
    def test_archive_failure_sends_nothing(self, post):
        with patch.object(Path, 'write_bytes', side_effect=OSError('disk full')):
            deliver_one(self.delivery.pk)
        post.assert_not_called()
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, 'failed')
