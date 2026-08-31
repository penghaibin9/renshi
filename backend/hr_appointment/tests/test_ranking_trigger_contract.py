import importlib
import inspect

from django.test import SimpleTestCase


class Hr14RankingTriggerContractTests(SimpleTestCase):
    def test_ranking_trigger_migration_is_non_atomic_and_bidirectional(self):
        migration = importlib.import_module(
            "hr_appointment.migrations.0016_ranking_fact_seal"
        )
        source = inspect.getsource(migration)

        self.assertFalse(migration.Migration.atomic)
        self.assertIn("hr14_ranking_reject_update", source)
        self.assertIn("hr14_ranking_reject_delete", source)
        self.assertIn("drop_mysql_ranking_triggers", source)
