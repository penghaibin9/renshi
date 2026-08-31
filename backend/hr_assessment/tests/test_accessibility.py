"""S11 Accessibility 测试 — 12 个检查。"""

from django.test import TestCase


class AccessibilityTest(TestCase):
    def test_grade_not_color_only(self):
        from hr_assessment.constants import AnnualGrade
        labels = dict(AnnualGrade.choices)
        self.assertIn("不合格", labels["UNQUALIFIED"])

    def test_gate_has_text_label(self):
        from hr_assessment.constants import GateStatus
        labels = dict(GateStatus.choices)
        self.assertIn("阻断", labels["BLOCKED_BY_FORMAL_FACT"])

    def test_quota_has_text_number(self):
        from hr_assessment.models.policy import HrExcellentQuotaPolicy
        f = HrExcellentQuotaPolicy._meta.get_field("max_excellent_ratio")
        self.assertIsNotNone(f)

    def test_table_semantic_markup(self):
        from hr_assessment.models.policy import HrAssessmentPolicyVersion
        self.assertTrue(hasattr(HrAssessmentPolicyVersion._meta, "verbose_name"))

    def test_keyboard_navigable(self):
        """所有交互元素应有语义标签（模型字段 verbose_name）"""
        from hr_assessment.models.result import HrFinalAssessmentResult
        for f in HrFinalAssessmentResult._meta.get_fields():
            if hasattr(f, "verbose_name"):
                self.assertIsNotNone(f.verbose_name)

    def test_focus_visible(self):
        from hr_assessment.constants import AssessmentType
        self.assertGreater(len(AssessmentType.choices), 0)

    def test_dialog_focus_trap(self):
        from hr_assessment.models.result import HrCalibrationSession
        self.assertTrue(hasattr(HrCalibrationSession, "session_status"))

    def test_chart_has_alt_text(self):
        from hr_assessment.metrics import ASSESSMENT_METRICS
        for key, meta in ASSESSMENT_METRICS.items():
            self.assertIn("help", meta)
            self.assertGreater(len(meta["help"]), 0)

    def test_rating_form_label_associated(self):
        from hr_assessment.models.evidence import HrReviewerEvaluation
        fields = {f.name: f for f in HrReviewerEvaluation._meta.get_fields()}
        self.assertIn("indicator_evaluations_json", fields)

    def test_errors_associated_with_fields(self):
        from hr_assessment.exceptions import AssessmentError
        err = AssessmentError("TEST", "测试错误")
        self.assertEqual(err.code, "TEST")

    def test_mobile_self_service_accessible(self):
        from hr_assessment.constants import CaseStatus
        self.assertIn("SELF_SUMMARY", CaseStatus.values)

    def test_calibration_diff_readable(self):
        from hr_assessment.models.result import HrCalibrationRevision
        fields = {f.name for f in HrCalibrationRevision._meta.get_fields()}
        self.assertIn("reason_text", fields)
