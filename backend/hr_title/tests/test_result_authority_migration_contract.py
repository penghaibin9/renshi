import importlib
import inspect

from django.test import SimpleTestCase


class Hr13ResultAuthorityMigrationContractTests(SimpleTestCase):
    def test_mysql_trigger_migration_is_non_atomic_and_seals_every_authority_parent(self):
        migration = importlib.import_module(
            "hr_title.migrations.0010_title_result_authority_boundary"
        )
        self.assertFalse(migration.Migration.atomic)
        source = inspect.getsource(migration)
        for trigger in (
            "hr13_title_result_no_update",
            "hr13_title_result_no_delete",
            "hr13_review_ballot_insert_guard",
            "hr13_review_ballot_no_update",
            "hr13_review_ballot_no_delete",
            "hr13_review_round_insert_guard",
            "hr13_review_round_write_seal_upd",
            "hr13_review_round_write_seal_del",
            "hr13_title_policy_no_update",
            "hr13_title_policy_no_delete",
            "hr13_title_application_identity_upd",
            "hr13_title_application_no_delete",
        ):
            self.assertIn(trigger, source)

