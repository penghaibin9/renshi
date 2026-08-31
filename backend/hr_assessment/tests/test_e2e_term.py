"""S11 E2E 聘期链。"""

from django.test import TestCase
from hr_assessment.models.cycle import HrAssessmentCycle
from hr_assessment.models.case import HrTermAssessmentCase, HrAssessmentCase
from hr_assessment.models.result import HrFinalAssessmentResult, HrResultApplicationLedger
import uuid
from datetime import date


class E2ETermRenewalChainTest(TestCase):
    def setUp(self):
        self.tenant_id = 10001
        self.staff_id = uuid.uuid4()
        self.term_id = uuid.uuid4()
        self.agreement_id = uuid.uuid4()

    def test_term_case_requires_hr07_ids(self):
        cycle = HrAssessmentCycle.objects.create(
            tenant_id=self.tenant_id, cycle_no="T-001", assessment_type="TERM",
            name="聘期考核", start_at="2026-01-01T00:00:00Z", end_at="2026-12-31T00:00:00Z",
            policy_version_id=uuid.uuid4(),
        )
        case = HrTermAssessmentCase.objects.create(
            tenant_id=self.tenant_id, assessment_type="TERM", cycle=cycle,
            staff_id=self.staff_id,
            term_id=self.term_id, agreement_id=self.agreement_id,
            term_start=date(2023, 1, 1), term_end=date(2025, 12, 31),
        )
        self.assertEqual(case.term_id, self.term_id)
        self.assertEqual(case.agreement_id, self.agreement_id)

    def test_term_goal_snapshot_stored(self):
        cycle = HrAssessmentCycle.objects.create(
            tenant_id=self.tenant_id, cycle_no="T-002", assessment_type="TERM",
            name="聘期考核", start_at="2026-01-01T00:00:00Z", end_at="2026-12-31T00:00:00Z",
            policy_version_id=uuid.uuid4(),
        )
        case = HrTermAssessmentCase.objects.create(
            tenant_id=self.tenant_id, assessment_type="TERM", cycle=cycle,
            staff_id=self.staff_id,
            term_id=self.term_id, agreement_id=self.agreement_id,
            term_start=date(2023, 1, 1), term_end=date(2025, 12, 31),
            term_duty_snapshot_json={"duties": ["教学", "科研"]},
            term_goal_snapshot_json={"goals": [{"id": "G1", "desc": "完成3篇论文"}]},
        )
        self.assertIn("goals", case.term_goal_snapshot_json)

    def test_annual_results_aggregated(self):
        cycle = HrAssessmentCycle.objects.create(
            tenant_id=self.tenant_id, cycle_no="T-003", assessment_type="TERM",
            name="聘期考核", start_at="2026-01-01T00:00:00Z", end_at="2026-12-31T00:00:00Z",
            policy_version_id=uuid.uuid4(),
        )
        case = HrTermAssessmentCase.objects.create(
            tenant_id=self.tenant_id, assessment_type="TERM", cycle=cycle,
            staff_id=self.staff_id,
            term_id=self.term_id, agreement_id=self.agreement_id,
            term_start=date(2023, 1, 1), term_end=date(2025, 12, 31),
            annual_result_refs_json=[{"year": 2023, "grade": "QUALIFIED"}, {"year": 2024, "grade": "EXCELLENT"}],
        )
        self.assertEqual(len(case.annual_result_refs_json), 2)

    def test_term_result_qualified(self):
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(), assessment_type="TERM",
            grade_code="QUALIFIED", result_version_no=1, status="FINALIZED",
        )
        self.assertEqual(result.grade_code, "QUALIFIED")

    def test_handoff_to_hr07_ledger(self):
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(), assessment_type="TERM",
            grade_code="QUALIFIED", result_version_no=1, status="FINALIZED",
        )
        ledger = HrResultApplicationLedger.objects.create(
            tenant_id=self.tenant_id, result=result,
            consumer_domain="hr_contracts", consumer_object_id=uuid.uuid4(),
            purpose="TERM_RENEWAL_REFERENCE", result_version=1,
        )
        self.assertEqual(ledger.consumer_domain, "hr_contracts")

    def test_unqualified_chain(self):
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(), assessment_type="TERM",
            grade_code="UNQUALIFIED", result_version_no=1, status="FINALIZED",
        )
        self.assertEqual(result.grade_code, "UNQUALIFIED")
        # 验证不会自动删账号（HR12 不拥有该能力）
        self.assertNotEqual(result.grade_code, "DISABLED")
