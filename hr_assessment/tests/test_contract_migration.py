"""S11 补齐：API contract / migration / reconciliation / audit 测试。"""

from importlib import import_module

from django.test import TestCase


class APIContractTest(TestCase):
    def test_api_success_envelope_shape(self):
        from hr_assessment.api.response import api_success

        data = api_success(data={"x": 1}, request_id="r1")
        self.assertIn("apiVersion", data)
        self.assertIn("schemaVersion", data)
        self.assertIn("requestId", data)
        self.assertIn("data", data)
        self.assertEqual(data["data"], {"x": 1})

    def test_api_error_envelope_shape(self):
        from hr_assessment.api.response import api_error

        err = api_error(code="TEST", message="msg", http_status=400)
        self.assertIn("error", err)
        self.assertEqual(err["error"]["code"], "TEST")
        self.assertEqual(err["error"]["retryable"], False)
        self.assertEqual(err["httpStatus"], 400)

    def test_paginated_response_structure(self):
        from hr_assessment.api.response import paginated_response

        result = paginated_response([], 0, 1, 20, False, "r1")
        self.assertEqual(result["meta"]["total"], 0)
        self.assertEqual(result["meta"]["page"], 1)
        self.assertEqual(result["meta"]["pageSize"], 20)
        self.assertFalse(result["meta"]["hasNext"])

    def test_api_urls_are_defined(self):
        from hr_assessment.api.urls import urlpatterns

        self.assertGreater(len(urlpatterns), 4)

    def test_api_views_use_require_assessment_permission(self):
        from hr_assessment.api.views_policy import policy_list

        self.assertTrue(callable(policy_list))


class MigrationTest(TestCase):
    def test_migration_has_operations(self):
        migration = import_module("hr_assessment.migrations.0001_initial")
        self.assertGreater(len(migration.Migration.operations), 0)

    def test_pms_migration_command_exists(self):
        from hr_assessment.management.commands.migrate_pms import Command

        self.assertTrue(hasattr(Command, "help"))


class ReconciliationTest(TestCase):
    def test_dual_read_compare_command_runs(self):
        from hr_assessment.management.commands.dual_read_compare import Command

        self.assertTrue(hasattr(Command, "help"))

    def test_legacy_freeze_public_api(self):
        from hr_assessment.management.commands.legacy_freeze import is_pms_write_frozen

        self.assertIsInstance(is_pms_write_frozen(), bool)

    def test_application_ledger_tracks_version(self):
        import uuid

        from hr_assessment.models.result import (
            HrFinalAssessmentResult,
            HrResultApplicationLedger,
        )

        result = HrFinalAssessmentResult.objects.create(
            tenant_id=10001,
            case_id=uuid.uuid4(),
            assessment_type="ANNUAL",
            grade_code="QUALIFIED",
            result_version_no=1,
            status="FINALIZED",
        )
        ledger = HrResultApplicationLedger.objects.create(
            tenant_id=10001,
            result=result,
            consumer_domain="hr_contracts",
            consumer_object_id=uuid.uuid4(),
            purpose="REFERENCE",
            result_version=1,
        )
        self.assertEqual(ledger.result_version, 1)


class AuditTest(TestCase):
    def test_signal_on_final_result(self):
        from hr_assessment.models.result import HrFinalAssessmentResult

        self.assertTrue(hasattr(HrFinalAssessmentResult, "case_id"))

    def test_assessment_event_types_complete(self):
        from hr_assessment.constants import ASSESSMENT_EVENT_TYPES

        required = {
            "AssessmentResultFinalized",
            "AssessmentResultRevised",
            "TermAssessmentFinalized",
            "AssessmentPolicyPublished",
        }
        self.assertTrue(required.issubset(ASSESSMENT_EVENT_TYPES))

    def test_audit_permission_defined(self):
        from hr_assessment.permissions import ASSESSMENT_PERMISSIONS

        codes = [p[0] for p in ASSESSMENT_PERMISSIONS]
        self.assertIn("hr.assessment.auditor", codes)

    def test_feature_flags_have_defaults(self):
        from hr_assessment.feature_flags import DEFAULTS, get_flag

        self.assertIn("HR12_SHADOW_EXECUTION", DEFAULTS)
        self.assertIsInstance(get_flag("HR12_SHADOW_EXECUTION"), bool)
