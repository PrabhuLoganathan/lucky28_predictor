from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.utils import timezone

from games.alert_forms import AlertDestinationForm, AlertRuleForm
from games.group_config import COLOR_GROUPS
from games.models import (AlertDelivery, AlertDestination, AlertRule, GameRound,
                          GroupAbsenceState)
from games.services.alert_delivery import deliver_one
from games.services.alerts import record_live_event, check_collection_health, eligible_destinations
from games.services.group_absence import save_settings, synchronize


@override_settings(ALERT_TELEGRAM_ENABLED=True, ALERT_TELEGRAM_BOT_TOKEN='test-token')
class DirectRoutingTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        settings = override_settings(ALERT_STATE_DIR=Path(self.directory.name))
        settings.enable()
        self.addCleanup(settings.disable)
        self.level = AlertDestination.objects.create(name='Level 5', chat_id='123', plan_rank=5,
            enabled=True, use_cards=False, send_results=True)
        self.direct = AlertDestination.objects.create(name='Lucky28(Wheel) - Group Absence Alerts',
            chat_id='456', routing_type='direct', enabled=True, use_cards=False, send_results=True)
        self.rule = AlertRule.objects.create(key='every', title='Every round', series='number',
            mode='every_game', min_plan_rank=5, send_to_levels=False)
        self.rule.destinations.add(self.direct)
        self.local = dict(REMOTE_ADDR='127.0.0.1', HTTP_HOST='localhost')

    def route_rule(self, *destinations, levels=False):
        self.rule.send_to_levels = levels
        self.rule.save()
        self.rule.destinations.set(destinations)

    def pre(self, index=0):
        game = GameRound.objects.create(game_no=f'current{index}', game_type='lucky28',
            has_pre=True, pre_event_ts=self.now + timedelta(seconds=index))
        record_live_event(game, 'pre')
        return game

    def result(self, index, number):
        GameRound.objects.create(game_no=f'R{index}', game_type='lucky28', has_winner=True,
            winning_number=number, status=3, winner_event_ts=self.now - timedelta(seconds=30-index))
        synchronize()

    def configure_groups(self, target, levels=None):
        values = {g.id: dict(enabled=g.id == 'G01', threshold=2 if g.id == 'G01' else None,
            ending_enabled=g.id == 'G01', ending_threshold=2 if g.id == 'G01' else None,
            send_to_levels=(target is None if levels is None else levels) if g.id == 'G01' else True,
            destination_ids=[target] if target and g.id == 'G01' else []) for g in COLOR_GROUPS}
        save_settings('lucky28', True, values, 'test')

    @patch('games.services.alert_delivery.requests.post')
    def test_direct_rule_ignores_rank_and_delivers_only_to_selected_channel(self, post):
        self.pre()
        delivery = AlertDelivery.objects.get(kind='alert')
        self.assertEqual(delivery.destination, self.direct)
        post.return_value = Mock(status_code=200, json=lambda: {'ok': True, 'result': {'message_id': 42}})
        deliver_one(delivery.pk)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'sent')
        self.assertEqual(post.call_args.kwargs['data']['chat_id'], '456')

    def test_hierarchy_and_general_broadcasts_exclude_direct_channels(self):
        self.route_rule(levels=True)
        self.pre()
        self.assertEqual(AlertDelivery.objects.get(kind='alert').destination, self.level)
        self.assertEqual(list(eligible_destinations(self.now)), [self.level])
        check_collection_health(self.now)
        check_collection_health(self.now + timedelta(minutes=4))
        self.assertEqual(AlertDelivery.objects.get(kind='health').destination, self.level)
        self.configure_groups(None)
        for i, number in enumerate([0, 8, 8, 0]):
            self.result(i, number)
        self.assertEqual(list(AlertDelivery.objects.filter(kind__in=['group', 'group_end'])
            .values_list('destination_id', flat=True)), [self.level.pk, self.level.pk])

    def test_disabled_or_expired_direct_target_never_falls_back(self):
        self.direct.enabled = False
        self.direct.save()
        self.pre()
        self.direct.enabled = True
        self.direct.expires_at = self.now - timedelta(seconds=1)
        self.direct.save()
        self.pre(1)
        self.assertFalse(AlertDelivery.objects.exists())
        self.configure_groups(self.direct.pk)
        for i, number in enumerate([0, 8, 8, 0]):
            self.result(i, number)
        self.assertFalse(AlertDelivery.objects.exists())

    @patch('games.services.alert_delivery.requests.post')
    def test_queued_rule_cancelled_after_target_change(self, post):
        self.pre()
        delivery = AlertDelivery.objects.get(kind='alert')
        self.route_rule(self.level)
        deliver_one(delivery.pk)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'cancelled')
        post.assert_not_called()

    @patch('games.services.alert_delivery.requests.post')
    def test_queued_broadcast_cancelled_when_destination_becomes_direct(self, post):
        self.route_rule(levels=True)
        self.pre()
        delivery = AlertDelivery.objects.get(kind='alert')
        self.level.routing_type = 'direct'
        self.level.save()
        deliver_one(delivery.pk)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'cancelled')
        post.assert_not_called()

    @patch('games.services.alert_delivery.requests.post')
    def test_routing_change_during_render_cancels_send(self, post):
        self.pre()
        delivery = AlertDelivery.objects.get(kind='alert')
        delivery.payload['use_cards'] = True
        delivery.save()
        def change_route(*args):
            self.route_rule(self.level)
        with patch('games.services.alert_delivery.card_with_deadline', side_effect=change_route):
            deliver_one(delivery.pk)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'cancelled')
        post.assert_not_called()

    @patch('games.services.alert_delivery.requests.post')
    def test_result_follows_direct_alert_and_respects_route_change(self, post):
        game = self.pre()
        post.return_value = Mock(status_code=200, json=lambda: {'ok': True, 'result': {'message_id': 42}})
        deliver_one(AlertDelivery.objects.get(kind='alert').pk)
        game.has_winner, game.winning_number, game.winner_event_ts = True, 0, self.now
        game.save()
        record_live_event(game, 'winner')
        result = AlertDelivery.objects.get(kind='result')
        self.assertEqual(result.destination, self.direct)
        deliver_one(result.pk)
        result.refresh_from_db()
        self.assertEqual(result.status, 'sent')
        self.route_rule(levels=True)
        # A queued result is revalidated even if its original was confirmed sent.
        AlertDelivery.objects.filter(pk=result.pk).update(status='pending')
        post.reset_mock()
        deliver_one(result.pk)
        result.refresh_from_db()
        self.assertEqual(result.status, 'cancelled')
        post.assert_not_called()

    @patch('games.services.alert_delivery.requests.post')
    def test_group_absence_and_return_share_direct_target(self, post):
        self.configure_groups(self.direct.pk)
        for i, number in enumerate([0, 8, 8]):
            self.result(i, number)
        absence = AlertDelivery.objects.get(kind='group')
        self.assertEqual(absence.destination, self.direct)
        post.return_value = Mock(status_code=200, json=lambda: {'ok': True, 'result': {'message_id': 42}})
        deliver_one(absence.pk)
        absence.refresh_from_db()
        self.assertEqual(absence.status, 'sent')
        self.result(3, 0)
        ending = AlertDelivery.objects.get(kind='group_end')
        self.assertEqual(ending.destination, self.direct)
        deliver_one(ending.pk)
        ending.refresh_from_db()
        self.assertEqual(ending.status, 'sent')
        self.assertFalse(AlertDelivery.objects.filter(destination=self.level).exists())

    @patch('games.services.alert_delivery.requests.post')
    def test_group_queue_rechecks_current_route(self, post):
        self.configure_groups(None)
        for i, number in enumerate([0, 8, 8]):
            self.result(i, number)
        old = AlertDelivery.objects.get(kind='group')
        self.configure_groups(self.direct.pk)
        self.assertTrue(AlertDelivery.objects.filter(kind='group', destination=self.direct).exists())
        deliver_one(old.pk)
        old.refresh_from_db()
        self.assertEqual(old.status, 'cancelled')
        self.result(3, 0)
        ending = AlertDelivery.objects.get(kind='group_end')
        self.configure_groups(None)
        deliver_one(ending.pk)
        ending.refresh_from_db()
        self.assertEqual(ending.status, 'cancelled')
        post.assert_not_called()

    def test_forms_save_without_level_and_require_valid_channel(self):
        form = AlertDestinationForm(dict(name='Direct', chat_id='@direct_channel', routing_type='direct'))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().routing_type, 'direct')
        data = dict(title='Direct rule', series='number', mode='every_game', recipients=[str(self.direct.pk)])
        form = AlertRuleForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(list(form.save().destinations.all()), [self.direct])
        self.assertFalse(AlertRuleForm(dict(data, recipients=['999999'])).is_valid())
        self.assertFalse(AlertRuleForm(dict(data, recipients=[])).is_valid())
        self.assertFalse(AlertDestinationForm(dict(name='Level', chat_id='@level_channel', routing_type='level')).is_valid())

    def test_group_form_persists_and_displays_routing(self):
        self.configure_groups(None)
        data = {'enabled': 'on', 'G01_enabled': 'on', 'G01_threshold': '2',
                'G01_recipients': [str(self.direct.pk)]}
        response = self.client.post('/alerts/groups/settings/', data, **self.local)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(GroupAbsenceState.objects.get(stream_id='lucky28', group_id='G01').destinations.all()), [self.direct])
        response = self.client.get('/alerts/groups/settings/', **self.local)
        self.assertContains(response, 'Send all groups to')
        self.assertContains(self.client.get('/alerts/rules/', **self.local), f'Only: {self.direct.name}')
        self.assertContains(self.client.get('/alerts/destinations/', **self.local), 'Direct only')
        self.assertEqual(self.client.post('/alerts/groups/settings/', dict(data, G01_recipients=['999999']),
            **self.local).status_code, 400)
        self.assertEqual(list(GroupAbsenceState.objects.get(stream_id='lucky28', group_id='G01').destinations.all()), [self.direct])

    def test_assigned_destination_is_disabled_instead_of_deleted(self):
        response = self.client.post(f'/alerts/destinations/{self.direct.pk}/delete/', **self.local)
        self.assertEqual(response.status_code, 302)
        self.direct.refresh_from_db()
        self.assertFalse(self.direct.enabled)
        self.rule.refresh_from_db()
        self.assertEqual(list(self.rule.destinations.all()), [self.direct])

    @patch('games.services.alert_delivery.requests.post')
    def test_combined_rule_routes_deduplicate_and_respect_levels(self, post):
        lower = AlertDestination.objects.create(name='Lower', chat_id='789', plan_rank=1, enabled=True)
        self.route_rule(self.direct, self.level, levels=True)
        self.pre()
        deliveries = list(AlertDelivery.objects.filter(kind='alert'))
        self.assertCountEqual([d.destination_id for d in deliveries], [self.direct.pk, self.level.pk])
        post.return_value = Mock(status_code=200, json=lambda: {'ok': True, 'result': {'message_id': 42}})
        for delivery in deliveries:
            deliver_one(delivery.pk)
        self.assertEqual(post.call_count, 2)
        self.assertFalse(AlertDelivery.objects.filter(destination=lower).exists())
        # Explicitly selecting a low-level channel bypasses its rank, too.
        self.route_rule(self.direct, lower, levels=True)
        self.pre(1)
        self.assertEqual(AlertDelivery.objects.filter(kind='alert', evaluation__game_no='current1').count(), 3)

    def test_multiple_channels_without_hierarchy(self):
        second = AlertDestination.objects.create(name='Second direct', chat_id='789', routing_type='direct', enabled=True)
        self.route_rule(self.direct, second)
        self.pre()
        self.assertCountEqual(AlertDelivery.objects.values_list('destination_id', flat=True), [self.direct.pk, second.pk])
        self.assertFalse(AlertDelivery.objects.filter(destination=self.level).exists())

    @patch('games.services.alert_delivery.requests.post')
    def test_removing_channel_keeps_other_queued_recipients(self, post):
        self.route_rule(self.direct, self.level, levels=True)
        self.pre()
        direct_delivery = AlertDelivery.objects.get(destination=self.direct)
        level_delivery = AlertDelivery.objects.get(destination=self.level)
        self.route_rule(levels=True)
        post.return_value = Mock(status_code=200, json=lambda: {'ok': True, 'result': {'message_id': 42}})
        deliver_one(direct_delivery.pk)
        deliver_one(level_delivery.pk)
        direct_delivery.refresh_from_db()
        level_delivery.refresh_from_db()
        self.assertEqual(direct_delivery.status, 'cancelled')
        self.assertEqual(level_delivery.status, 'sent')
        post.assert_called_once()

    def test_combined_group_routes_deduplicate_absence_and_return(self):
        self.configure_groups(self.direct.pk, levels=True)
        state = GroupAbsenceState.objects.get(group_id='G01')
        state.destinations.add(self.level)
        for index, number in enumerate([0, 8, 8, 0]):
            self.result(index, number)
        for kind in ('group', 'group_end'):
            self.assertCountEqual(AlertDelivery.objects.filter(kind=kind).values_list('destination_id', flat=True),
                                  [self.direct.pk, self.level.pk])

    def test_checkbox_form_round_trip_combined_and_revision(self):
        previous_revision = self.rule.revision
        data = dict(title=self.rule.title, series='number', mode='every_game', enabled='on',
            min_plan_rank=3, recipients=['levels', str(self.direct.pk), str(self.level.pk)])
        form = AlertRuleForm(data, instance=self.rule)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.rule.refresh_from_db()
        self.assertTrue(self.rule.send_to_levels)
        self.assertGreater(self.rule.revision, previous_revision)
        self.assertCountEqual(AlertRuleForm(instance=self.rule).initial['recipients'], data['recipients'])
        previous_revision = self.rule.revision
        self.rule.destinations.remove(self.level)
        self.assertGreater(self.rule.revision, previous_revision)
        # Reject an invalid or empty selection without altering saved recipients.
        response = self.client.post(f'/alerts/rules/{self.rule.pk}/edit/', dict(data, recipients=[]), **self.local)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(list(self.rule.destinations.all()), [self.direct])
        self.assertFalse(AlertRuleForm(dict(data, min_plan_rank='')).is_valid())
