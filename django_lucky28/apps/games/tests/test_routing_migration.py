from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class RecipientMigrationTests(TransactionTestCase):
    def test_existing_direct_and_hierarchy_choices_survive_upgrade(self):
        before = [('games', '0016_direct_alert_routing')]
        after = [('games', '0017_multiple_alert_recipients')]
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        try:
            apps = executor.loader.project_state(before).apps
            destination = apps.get_model('games', 'AlertDestination').objects.create(
                name='Dedicated', chat_id='-1003563158797', routing_type='direct')
            rule_model = apps.get_model('games', 'AlertRule')
            direct = rule_model.objects.create(key='migration-direct', title='Direct', series='number',
                mode='every_game', direct_destination_id=destination.pk, min_plan_rank=5, revision=8)
            hierarchy = rule_model.objects.create(key='migration-level', title='Hierarchy', series='number',
                mode='every_game', min_plan_rank=3)
            stream = apps.get_model('games', 'GroupAbsenceStream').objects.create(key='migration')
            state_model = apps.get_model('games', 'GroupAbsenceState')
            state = state_model.objects.create(stream=stream, group_id='G01', direct_destination_id=destination.pk)
            level_state = state_model.objects.create(stream=stream, group_id='G02')
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            apps = executor.loader.project_state(after).apps
            new_rule = apps.get_model('games', 'AlertRule').objects.get(pk=direct.pk)
            self.assertFalse(new_rule.send_to_levels)
            self.assertEqual(new_rule.revision, 8)
            self.assertEqual(new_rule.min_plan_rank, 5)
            self.assertEqual(list(new_rule.destinations.values_list('pk', flat=True)), [destination.pk])
            new_hierarchy = apps.get_model('games', 'AlertRule').objects.get(pk=hierarchy.pk)
            self.assertTrue(new_hierarchy.send_to_levels)
            self.assertEqual(new_hierarchy.min_plan_rank, 3)
            self.assertFalse(new_hierarchy.destinations.exists())
            new_state = apps.get_model('games', 'GroupAbsenceState').objects.get(pk=state.pk)
            self.assertFalse(new_state.send_to_levels)
            self.assertEqual(list(new_state.destinations.values_list('pk', flat=True)), [destination.pk])
            self.assertTrue(apps.get_model('games', 'GroupAbsenceState').objects.get(pk=level_state.pk).send_to_levels)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
