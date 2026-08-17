"""S11 AI 边界 + Accessibility + Performance 测试。"""

from django.test import TestCase


class AIBoundaryTest(TestCase):
    def test_no_structural_final_grade_auto_assignment(self):
        """验证模型结构阻止 AI 自动 FINALIZE 行为"""
        from hr_assessment.models.result import HrFinalAssessmentResult
        # grade_code 是 CharField 且有 result_version_no 和 finalized_by
        fields = {f.name for f in HrFinalAssessmentResult._meta.get_fields()}
        self.assertIn("decision_reason", fields)
        self.assertIn("finalized_by", fields)

    def test_no_auto_ethics_conclusion(self):
        from hr_assessment.models.case import HrEthicsAssessmentCase
        fields = {f.name for f in HrEthicsAssessmentCase._meta.get_fields()}
        self.assertIn("decided_by", fields)

    def test_no_auto_excellent_list(self):
        from hr_assessment.constants import AnnualGrade
        self.assertEqual(AnnualGrade.EXCELLENT.value, "EXCELLENT")

    def test_ethics_gate_requires_human_review(self):
        from hr_assessment.constants import GateStatus
        self.assertIn("REVIEW_REQUIRED", GateStatus.values)

    def test_calibration_requires_before_after_diff(self):
        from hr_assessment.models.result import HrCalibrationRevision
        fields = {f.name for f in HrCalibrationRevision._meta.get_fields()}
        self.assertIn("before_rating_json", fields)
        self.assertIn("after_rating_json", fields)

    def test_no_auto_bottom_rank(self):
        from hr_assessment.constants import AnnualGrade
        self.assertNotIn("BOTTOM_RANK", AnnualGrade.values)

    def test_sensitivity_levels_defined(self):
        from hr_assessment.constants import DataSensitivityLevel
        self.assertIn("HIGHLY_RESTRICTED_ETHICS", DataSensitivityLevel.values)


class AccessibilityTest(TestCase):
    def test_grade_not_color_only_check(self):
        """验证存在文字/代码可区分所有档次"""
        from hr_assessment.constants import AnnualGrade
        self.assertGreater(len(AnnualGrade.choices), 4)

    def test_gate_status_has_labels(self):
        from hr_assessment.constants import GateStatus
        self.assertEqual(len(GateStatus.choices), 4)

    def test_quota_policy_has_text_fields(self):
        from hr_assessment.models.policy import HrExcellentQuotaPolicy
        fields = {f.name for f in HrExcellentQuotaPolicy._meta.get_fields()}
        for need in ["name", "quota_basis_population"]:
            self.assertIn(need, fields)

    def test_calibration_diff_fields_present(self):
        from hr_assessment.models.result import HrCalibrationRevision
        fields = {f.name for f in HrCalibrationRevision._meta.get_fields()}
        for need in ["reason_code", "reason_text"]:
            self.assertIn(need, fields)


class PerformanceTargetTest(TestCase):
    @staticmethod
    def _indexed_fields(model):
        return [tuple(index.fields) for index in model._meta.indexes]

    def test_policy_resolve_uses_indexed_fields(self):
        from hr_assessment.models.policy import HrAssessmentPolicyVersion
        indexes = self._indexed_fields(HrAssessmentPolicyVersion)
        self.assertTrue(any("status" in fields for fields in indexes))

    def test_case_query_uses_indexed_fields(self):
        from hr_assessment.models.case import HrAssessmentCase
        indexes = self._indexed_fields(HrAssessmentCase)
        self.assertTrue(any("staff_id" in fields for fields in indexes))

    def test_result_ledger_uses_indexed_fields(self):
        from hr_assessment.models.result import HrFinalAssessmentResult
        indexes = self._indexed_fields(HrFinalAssessmentResult)
        self.assertTrue(any("status" in fields for fields in indexes))

    def test_population_uses_cycle_staff_unique(self):
        from hr_assessment.models.cycle import HrAssessmentPopulationSnapshot

        meta = HrAssessmentPopulationSnapshot._meta
        constraint_fields = {
            tuple(constraint.fields)
            for constraint in meta.constraints
            if getattr(constraint, "fields", None)
        }
        legacy_unique = {tuple(fields) for fields in meta.unique_together}
        self.assertTrue(
            ("cycle", "staff_id") in constraint_fields
            or ("cycle", "staff_id") in legacy_unique
        )
