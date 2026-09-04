from django.test import SimpleTestCase

from base.production_checks import (
    MYSQL_CONDITIONAL_UNIQUE_BACKSTOPS,
    conditional_unique_constraints,
    mysql_conditional_uniqueness_backstops,
)


class ProductionDatabaseContractTests(SimpleTestCase):
    def test_every_conditional_unique_constraint_has_mysql_backstop(self):
        self.assertEqual(
            conditional_unique_constraints(),
            MYSQL_CONDITIONAL_UNIQUE_BACKSTOPS,
        )
        self.assertEqual(mysql_conditional_uniqueness_backstops(), [])

    def test_expected_constraints_are_kept_explicit(self):
        self.assertEqual(len(MYSQL_CONDITIONAL_UNIQUE_BACKSTOPS), 6)
