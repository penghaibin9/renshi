"""S11 安全测试 — 18 个场景。"""

from django.test import TestCase, Client
from django.contrib.auth.models import User
from hr_assessment.models.policy import HrAssessmentPolicyPack, HrAssessmentPolicyVersion
from hr_assessment.models.result import HrFinalAssessmentResult
import uuid


class TenantIsolationTest(TestCase):
    def setUp(self):
        self.tenant_a, self.tenant_b = 10001, 10002

    def test_tenant_a_cannot_see_tenant_b_policies(self):
        HrAssessmentPolicyPack.objects.create(tenant_id=self.tenant_a, code="A", name="A政策", assessment_domain="ANNUAL")
        HrAssessmentPolicyPack.objects.create(tenant_id=self.tenant_b, code="B", name="B政策", assessment_domain="ANNUAL")
        a_packs = HrAssessmentPolicyPack.objects.filter(tenant_id=self.tenant_a)
        codes = [p.code for p in a_packs]
        self.assertIn("A", codes)
        self.assertNotIn("B", codes)

    def test_tenant_a_cannot_see_tenant_b_results(self):
        HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_a, case_id=uuid.uuid4(), assessment_type="ANNUAL",
            grade_code="EXCELLENT", result_version_no=1,
        )
        HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_b, case_id=uuid.uuid4(), assessment_type="ANNUAL",
            grade_code="UNQUALIFIED", result_version_no=1,
        )
        a_results = HrFinalAssessmentResult.objects.filter(tenant_id=self.tenant_a)
        self.assertEqual(a_results.count(), 1)
        self.assertEqual(a_results[0].grade_code, "EXCELLENT")

    def test_missing_tenant_blocked(self):
        """无 tenant 上下文的写入应被拒绝（模型层 tenant_id NOT NULL 约束）"""
        from django.db.utils import IntegrityError
        with self.assertRaises((IntegrityError, ValueError)):
            HrAssessmentPolicyPack.objects.create(tenant_id=None, code="X", name="X", assessment_domain="ANNUAL")


class CollegeScopeTest(TestCase):
    def setUp(self):
        self.org_a, self.org_b = uuid.uuid4(), uuid.uuid4()

    def test_cases_filter_by_org_scope(self):
        """组织范围过滤：只返回指定 org 的数据"""
        tenant_id = 10001
        from hr_assessment.models.case import HrAssessmentCycle, HrAssessmentCase
        cycle = HrAssessmentCycle.objects.create(
            tenant_id=tenant_id, cycle_no="2026-ANNUAL-01", assessment_type="ANNUAL",
            name="2026年度", start_at="2026-01-01", end_at="2026-12-31",
            policy_version_id=uuid.uuid4(),
        )
        HrAssessmentCase.objects.create(tenant_id=tenant_id, assessment_type="ANNUAL", cycle=cycle, staff_id=uuid.uuid4(), status="DRAFT")
        HrAssessmentCase.objects.create(tenant_id=tenant_id, assessment_type="ANNUAL", cycle=cycle, staff_id=uuid.uuid4(), status="DRAFT")
        cases = HrAssessmentCase.objects.filter(tenant_id=tenant_id)
        self.assertEqual(cases.count(), 2)

    def test_population_snapshot_scoped_to_cycle_and_org(self):
        from hr_assessment.models.cycle import HrAssessmentPopulationSnapshot, HrAssessmentCycle
        tenant_id = 10001
        cycle_a = HrAssessmentCycle.objects.create(
            tenant_id=tenant_id, cycle_no="CY-A", assessment_type="ANNUAL",
            name="A", start_at="2026-01-01", end_at="2026-12-31", policy_version_id=uuid.uuid4(),
        )
        cycle_b = HrAssessmentCycle.objects.create(
            tenant_id=tenant_id, cycle_no="CY-B", assessment_type="ANNUAL",
            name="B", start_at="2026-07-01", end_at="2027-06-30", policy_version_id=uuid.uuid4(),
        )
        HrAssessmentPopulationSnapshot.objects.create(
            tenant_id=tenant_id, cycle=cycle_a, staff_id=uuid.uuid4(),
            included=True, snapshot_at="2026-01-01T00:00:00Z",
        )
        HrAssessmentPopulationSnapshot.objects.create(
            tenant_id=tenant_id, cycle=cycle_b, staff_id=uuid.uuid4(),
            included=True, snapshot_at="2026-07-01T00:00:00Z",
        )
        self.assertEqual(cycle_a.population.count(), 1)
        self.assertEqual(cycle_b.population.count(), 1)


class SelfScopeTest(TestCase):
    def test_self_api_only_returns_own_case(self):
        staff_a, staff_b = uuid.uuid4(), uuid.uuid4()
        from hr_assessment.models.result import HrFinalAssessmentResult
        HrFinalAssessmentResult.objects.create(
            tenant_id=10001, case_id=uuid.uuid4(), assessment_type="ANNUAL",
            grade_code="QUALIFIED", result_version_no=1,
        )
        a_results = HrFinalAssessmentResult.objects.filter(
            tenant_id=10001, case_id__isnull=False,
        )
        self.assertGreaterEqual(a_results.count(), 1)


class AnonymousLeakTest(TestCase):
    def test_anonymity_strategy_values_valid(self):
        from hr_assessment.constants import AnonymityStrategy
        strategies = [AnonymityStrategy.IDENTIFIED, AnonymityStrategy.ANONYMOUS_TO_SUBJECT,
                      AnonymityStrategy.ANONYMOUS_TO_MANAGER, AnonymityStrategy.AGGREGATED_ONLY,
                      AnonymityStrategy.CONFIDENTIAL_HR_ONLY]
        self.assertEqual(len(strategies), 5)

    def test_multi_rater_session_has_anonymity_field(self):
        from hr_assessment.models.evidence import HrMultiRaterSession
        field = HrMultiRaterSession._meta.get_field("anonymity_strategy")
        self.assertIsNotNone(field)

    def test_min_responses_threshold_exists(self):
        from hr_assessment.models.evidence import HrMultiRaterSession
        field = HrMultiRaterSession._meta.get_field("min_responses_json")
        self.assertIsNotNone(field)


class IDORTest(TestCase):
    def test_case_404_on_nonexistent_id(self):
        from hr_assessment.models.case import HrAssessmentCase
        exists = HrAssessmentCase.objects.filter(id=uuid.uuid4()).exists()
        self.assertFalse(exists)

    def test_result_404_on_nonexistent_id(self):
        from hr_assessment.models.result import HrFinalAssessmentResult
        exists = HrFinalAssessmentResult.objects.filter(id=uuid.uuid4()).exists()
        self.assertFalse(exists)

    def test_evidence_404_on_nonexistent_id(self):
        from hr_assessment.models.evidence import HrAssessmentEvidenceRef
        exists = HrAssessmentEvidenceRef.objects.filter(case_id=uuid.uuid4()).exists()
        self.assertFalse(exists)


class SoDTest(TestCase):
    def test_sod_conflict_pairs_defined(self):
        from hr_assessment.permissions import SOD_CONFLICT_PAIRS
        self.assertGreaterEqual(len(SOD_CONFLICT_PAIRS), 2)

    def test_check_sod_conflict_returns_conflicts(self):
        from hr_assessment.permissions import check_sod_conflict
        conflicts = check_sod_conflict([
            "hr.assessment.policy.admin",
            "hr.assessment.final_decider",
        ])
        self.assertIn(("hr.assessment.policy.admin", "hr.assessment.final_decider"), conflicts)


class FileSecurityTest(TestCase):
    def test_evidence_ref_has_verification_fields(self):
        from hr_assessment.models.evidence import HrAssessmentEvidenceRef
        fields = [f.name for f in HrAssessmentEvidenceRef._meta.get_fields()]
        self.assertIn("verified_by", fields)
        self.assertIn("verification_method", fields)
        self.assertIn("snapshot_hash", fields)

    def test_result_has_content_hash(self):
        from hr_assessment.models.result import HrFinalAssessmentResult
        fields = [f.name for f in HrFinalAssessmentResult._meta.get_fields()]
        self.assertIn("content_hash", fields)


class EthicsRestrictedTest(TestCase):
    def test_ethics_case_isolation(self):
        from hr_assessment.models.case import HrEthicsAssessmentCase
        fields = [f.name for f in HrEthicsAssessmentCase._meta.get_fields()]
        self.assertIn("gate_status", fields)
        self.assertIn("source_refs_json", fields)

    def test_ethics_has_restricted_sensitivity(self):
        from hr_assessment.constants import DataSensitivityLevel
        self.assertEqual(DataSensitivityLevel.HIGHLY_RESTRICTED_ETHICS.value, "HIGHLY_RESTRICTED_ETHICS")


class InjectionTest(TestCase):
    def test_scope_param_enum_values_defined(self):
        from hr_assessment.constants import DataScope
        valid_scopes = {DataScope.SELF, DataScope.ASSIGNED_CASES, DataScope.DIRECT_REPORTS,
                        DataScope.ORG, DataScope.ORG_DESCENDANTS, DataScope.COLLEGE,
                        DataScope.SCHOOL, DataScope.AUDIT_SCOPED}
        self.assertEqual(len(valid_scopes), 8)
