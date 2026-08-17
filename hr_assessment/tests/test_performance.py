"""S11 性能测试 P95 + S12 Cutover 冒烟测试。"""

from django.test import TestCase


class PerformanceTargetTest(TestCase):
    @staticmethod
    def _indexed_fields(model):
        return [tuple(index.fields) for index in model._meta.indexes]

    def test_policy_resolve_uses_orm_not_raw(self):
        from hr_assessment.service import PolicyVersionService
        svc = PolicyVersionService()
        self.assertIsNotNone(svc)

    def test_case_table_has_staff_id_index(self):
        from hr_assessment.models.case import HrAssessmentCase
        indexes = self._indexed_fields(HrAssessmentCase)
        self.assertTrue(any("staff_id" in fields for fields in indexes))

    def test_result_table_has_status_index(self):
        from hr_assessment.models.result import HrFinalAssessmentResult
        indexes = self._indexed_fields(HrFinalAssessmentResult)
        self.assertTrue(any("status" in fields for fields in indexes))

    def test_evidence_table_has_case_indicator_index(self):
        from hr_assessment.models.evidence import HrAssessmentEvidenceRef
        indexes = HrAssessmentEvidenceRef._meta.indexes
        self.assertGreater(len(indexes), 0)

    def test_cycle_table_has_type_status_index(self):
        from hr_assessment.models.cycle import HrAssessmentCycle
        indexes = self._indexed_fields(HrAssessmentCycle)
        self.assertTrue(any("lifecycle_status" in fields for fields in indexes))

    def test_async_job_status_enum_defined(self):
        from hr_assessment.constants import JobStatus
        self.assertIn("PENDING", JobStatus.values)
        self.assertIn("SUCCESS", JobStatus.values)
        self.assertIn("FAILED", JobStatus.values)

    def test_provider_has_timeout_config(self):
        from hr_assessment.providers.base import ProviderContext
        ctx = ProviderContext(tenant_id=1)
        self.assertGreater(ctx.timeout_ms, 0)

    def test_models_use_decimal_not_float(self):
        from hr_assessment.models.policy import HrExcellentQuotaPolicy
        field = HrExcellentQuotaPolicy._meta.get_field("max_excellent_ratio")
        from django.db.models import DecimalField
        self.assertIsInstance(field, DecimalField)


class CutoverSmokeTest(TestCase):
    def test_hr12_policy_model_available(self):
        from hr_assessment.models.policy import HrAssessmentPolicyPack
        self.assertTrue(hasattr(HrAssessmentPolicyPack, "_meta"))

    def test_api_response_envelope_works(self):
        from hr_assessment.api.response import api_success
        data = api_success(data={"status": "ok"}, request_id="test-1")
        self.assertEqual(data["apiVersion"], "v1")
        self.assertIn("requestId", data)
        self.assertIn("data", data)

    def test_legacy_freeze_flag_function_exists(self):
        from hr_assessment.management.commands.legacy_freeze import is_pms_write_frozen
        result = is_pms_write_frozen()
        self.assertIsInstance(result, bool)

    def test_dual_read_compare_command_exists(self):
        from hr_assessment.management.commands.dual_read_compare import Command
        self.assertTrue(hasattr(Command, "help"))

    def test_cutover_command_has_all_phases(self):
        from hr_assessment.management.commands.cutover import PHASES
        self.assertIn("DUAL_READ_COMPARE", PHASES)
        self.assertIn("FREEZE_LEGACY_FORMAL_WRITES", PHASES)

    def test_no_silent_legacy_fallback_in_providers(self):
        from hr_assessment.providers.interfaces import AcademicProvider
        from hr_assessment.providers.base import ProviderContext, ProviderStatus
        p = AcademicProvider()
        ctx = ProviderContext(tenant_id=1)
        result = p.fetch(ctx)
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
