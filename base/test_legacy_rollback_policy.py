"""Rollback safety contract: entry rollback must never mutate new Authority facts."""

import inspect

from django.test import RequestFactory, SimpleTestCase

import horilla.legacy_hr_ui as legacy_hr_ui_module
from horilla.legacy_cutover_policy import (
    LEGACY_DEPRECATION_SUNSET,
    LEGACY_FORMAL_WRITER_ROLLBACK_ALLOWED,
    LEGACY_ROLLBACK_MODE,
    legacy_cutover_policy_snapshot,
)
from horilla.legacy_hr_api import legacy_hr_api_redirect


class LegacyHrRollbackSafetyTests(SimpleTestCase):
    def test_rollback_adapter_has_no_new_authority_dependencies_or_mutators(self):
        source = inspect.getsource(legacy_hr_ui_module)
        for forbidden in (
            "hr_payroll",
            "hr_exit",
            "hr_data",
            ".objects",
            ".save(",
            ".create(",
            ".update(",
            ".delete(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_rollback_successors_only_point_at_canonical_read_workspaces(self):
        self.assertEqual(
            legacy_hr_ui_module.LEGACY_HR_UI_SUCCESSORS,
            {
                "payroll": "/hr/payroll/",
                "offboarding": "/hr/exit/",
                "report": "/hr/data/",
            },
        )

    def test_policy_forbids_formal_writer_rollback(self):
        self.assertEqual(LEGACY_ROLLBACK_MODE, "ENTRY_ADAPTER_ONLY")
        self.assertIs(LEGACY_FORMAL_WRITER_ROLLBACK_ALLOWED, False)
        snapshot = legacy_cutover_policy_snapshot()
        self.assertEqual(snapshot["rollbackMode"], "ENTRY_ADAPTER_ONLY")
        self.assertIs(snapshot["formalWriterRollbackAllowed"], False)
        self.assertEqual(snapshot["sunset"], LEGACY_DEPRECATION_SUNSET)

    def test_ui_and_api_adapters_share_one_deprecation_contract(self):
        factory = RequestFactory()

        ui_request = factory.get("/offboarding/employee-view/?tenant=7")
        ui_response = legacy_hr_ui_module.legacy_hr_ui_redirect(
            ui_request,
            domain="offboarding",
            tail="employee-view/",
        )
        self.assertEqual(ui_response.status_code, 308)
        self.assertEqual(ui_response["Deprecation"], "true")
        self.assertEqual(ui_response["Sunset"], LEGACY_DEPRECATION_SUNSET)
        self.assertIn('rel="successor-version"', ui_response["Link"])

        api_request = factory.post("/api/hr/v1/payroll/periods/42/?tenant=7")
        api_response = legacy_hr_api_redirect(
            api_request,
            tail="payroll/periods/42/",
        )
        self.assertEqual(api_response.status_code, 308)
        self.assertEqual(api_response["Deprecation"], "true")
        self.assertEqual(api_response["Sunset"], LEGACY_DEPRECATION_SUNSET)
        self.assertIn('rel="successor-version"', api_response["Link"])
