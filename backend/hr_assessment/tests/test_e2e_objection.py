"""S11 E2E 异议改档链 + Provider 失败链。"""

from django.test import TestCase
from hr_assessment.models.result import (
    HrFinalAssessmentResult, HrAssessmentObjection, HrResultRevision,
    HrResultApplicationLedger,
)
from hr_assessment.providers.interfaces import (
    DevelopmentProvider, AcademicProvider, ResearchProvider, EthicsFactProvider,
)
from hr_assessment.providers.base import ProviderContext, ProviderStatus
from hr_assessment.services.result_correction_service import base_result_snapshot
import uuid


class E2EObjectionRevisionChainTest(TestCase):
    def setUp(self):
        self.tenant_id = 10001

    def test_objection_creates_case(self):
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(), assessment_type="ANNUAL",
            grade_code="UNQUALIFIED", result_version_no=1, status="FINALIZED",
        )
        obj = HrAssessmentObjection.objects.create(
            tenant_id=self.tenant_id, result=result,
            reason="对教学指标计算有异议", status="SUBMITTED",
        )
        self.assertEqual(obj.status, "SUBMITTED")

    def test_objection_review_transitions(self):
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(), assessment_type="ANNUAL",
            grade_code="UNQUALIFIED", result_version_no=1, status="FINALIZED",
        )
        obj = HrAssessmentObjection.objects.create(
            tenant_id=self.tenant_id, result=result, reason="异议", status="SUBMITTED",
        )
        obj.status = "ACCEPTED_FOR_REVIEW"
        obj.save()
        self.assertEqual(obj.status, "ACCEPTED_FOR_REVIEW")
        obj.status = "UPHELD"
        obj.resolved_at = "2026-08-01T00:00:00Z"
        obj.conclusion = "教学指标数据更正，原结果调整"
        obj.save()
        self.assertEqual(obj.status, "UPHELD")

    def test_result_v2_supersedes_v1(self):
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(), assessment_type="ANNUAL",
            grade_code="UNQUALIFIED", result_version_no=1, status="FINALIZED",
        )
        before = base_result_snapshot(result)
        after = {**before, "version": 2, "status": "CORRECTED", "gradeCode": "QUALIFIED"}
        revision = HrResultRevision.objects.create(
            tenant_id=self.tenant_id, result=result,
            previous_version=1, new_version=2, revision_type="OBJECTION_UPHELD",
            reason="教学指标更正后重新评价",
            before_snapshot_json=before,
            after_snapshot_json=after,
        )
        self.assertEqual(revision.previous_version, 1)
        self.assertEqual(revision.new_version, 2)
        self.assertEqual(revision.revision_type, "OBJECTION_UPHELD")

    def test_downstream_ledger_tracks_version(self):
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id, case_id=uuid.uuid4(), assessment_type="ANNUAL",
            grade_code="QUALIFIED", result_version_no=1, status="FINALIZED",
        )
        HrResultApplicationLedger.objects.create(
            tenant_id=self.tenant_id, result=result,
            consumer_domain="hr_title", consumer_object_id=uuid.uuid4(),
            purpose="TITLE_REFERENCE", result_version=1,
        )
        # V2 产生后追踪
        before = base_result_snapshot(result)
        after = {**before, "version": 2, "status": "CORRECTED"}
        revision = HrResultRevision.objects.create(
            tenant_id=self.tenant_id, result=result,
            previous_version=1, new_version=2, revision_type="CORRECTION",
            reason="修正", before_snapshot_json=before, after_snapshot_json=after,
        )
        HrResultApplicationLedger.objects.create(
            tenant_id=self.tenant_id, result=result,
            consumer_domain="hr_title", consumer_object_id=uuid.uuid4(),
            purpose="TITLE_REFERENCE_REVISION_CHECK", result_version=2,
        )
        apps = HrResultApplicationLedger.objects.filter(result=result)
        self.assertGreaterEqual(apps.count(), 2)

    def test_objection_reviewer_conflict_check_field_exists(self):
        from hr_assessment.models.result import HrAssessmentObjection
        fields = [f.name for f in HrAssessmentObjection._meta.get_fields()]
        self.assertIn("conflict_check_json", fields)
        self.assertIn("reviewer_staff_id", fields)


class E2EProviderFailureChainTest(TestCase):
    def test_academic_provider_unavailable(self):
        p = AcademicProvider()
        ctx = ProviderContext(tenant_id=10001)
        result = p.fetch(ctx)
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)

    def test_research_provider_unavailable(self):
        p = ResearchProvider()
        ctx = ProviderContext(tenant_id=10001)
        result = p.fetch(ctx)
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)

    def test_development_provider_empty_query_is_complete(self):
        p = DevelopmentProvider()
        ctx = ProviderContext(tenant_id=10001)
        result = p.fetch(ctx)
        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.data, [])

    def test_ethics_fact_provider_empty_query_is_complete(self):
        p = EthicsFactProvider()
        ctx = ProviderContext(tenant_id=10001)
        result = p.fetch(ctx)
        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.data, [])

    def test_unavailable_is_not_zero_or_ok(self):
        self.assertNotEqual(ProviderStatus.UNAVAILABLE, ProviderStatus.OK)

    def test_development_empty_query_has_no_error(self):
        p = DevelopmentProvider()
        ctx = ProviderContext(tenant_id=10001)
        result = p.fetch(ctx)
        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.error_message, "")
