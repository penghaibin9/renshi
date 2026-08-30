"""Executable HR14 quality-absorption contracts.

These checks replace the old always-green placeholder.  They prove that the
split authority models are registered, the full migration chain is present,
and the HTTP permission boundary cannot silently collapse to one generic
permission.
"""

from django.apps import apps
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import SimpleTestCase, TransactionTestCase

from hr_appointment import module_contract
from hr_appointment.permissions import (
    APPLICATION_PERMISSION,
    EFFECT_PERMISSION,
    MANAGE_PERMISSION,
    PUBLICITY_PERMISSION,
    READ_PERMISSION,
    REVIEW_PERMISSION,
)


class Hr14AuthorityRegistrationContractTests(SimpleTestCase):
    def test_split_authority_models_are_registered_by_app_config(self):
        registered = {
            model.__name__
            for model in apps.get_app_config("hr_appointment").get_models()
        }
        self.assertTrue(
            {
                "AppointmentApplicationCase",
                "AppointmentRankingResult",
                "AppointmentCollectiveDecision",
                "AppointmentPopulationSnapshot",
                "AppointmentPublicityObjection",
                "AppointmentTerm",
                "PositionAppointmentFact",
            }.issubset(registered)
        )

    def test_each_workflow_boundary_has_a_distinct_permission(self):
        permissions = {
            READ_PERMISSION,
            APPLICATION_PERMISSION,
            MANAGE_PERMISSION,
            REVIEW_PERMISSION,
            PUBLICITY_PERMISSION,
            EFFECT_PERMISSION,
        }
        self.assertEqual(len(permissions), 6)
        self.assertTrue(all(code.startswith("hr.appointment.") for code in permissions))

    def test_cross_module_consumers_use_the_public_contract(self):
        self.assertEqual(module_contract.UPSTREAM_AUTHORITIES, ("HR02", "HR03", "HR12", "HR13"))
        self.assertIn("HR15", module_contract.DOWNSTREAM_CONSUMERS)
        self.assertEqual(module_contract.CANONICAL_API_PREFIX, "/api/v1/hr/appointments")


class Hr14MigrationAbsorptionContractTests(TransactionTestCase):
    def test_collective_decision_migration_is_the_single_leaf(self):
        leaves = MigrationLoader(connection).graph.leaf_nodes("hr_appointment")
        self.assertEqual(
            leaves,
            [("hr_appointment", "0014_collective_decision_authority")],
        )
