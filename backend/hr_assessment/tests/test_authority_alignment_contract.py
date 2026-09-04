"""HR12 must use HR02 identities and server-owned result authority."""

import inspect
from pathlib import Path

from django.db import models
from django.test import SimpleTestCase

from hr_assessment.models.case import HrSubjectSnapshot
from hr_assessment.models.cycle import (
    HrAssessmentCycle,
    HrAssessmentPopulationSnapshot,
)
from hr_assessment.models.policy import HrAssessmentPolicyPack
from hr_assessment.models.result import HrAssessmentDecisionSession
from hr_assessment.selectors.cycle_utils import OrgAsOfResolver
from hr_assessment.services.finalization_service import AssessmentFinalizationService
from hr_assessment.api import views_policy
from hr_assessment.models.base import VersionedModel, calculate_version_content_hash


class AssessmentAuthorityAlignmentContractTests(SimpleTestCase):
    def test_hr02_references_use_integer_stable_ids(self):
        for model, field_name in (
            (HrAssessmentPolicyPack, "owner_org_id"),
            (HrAssessmentCycle, "owner_org_id"),
            (HrAssessmentPopulationSnapshot, "org_id"),
            (HrAssessmentPopulationSnapshot, "position_id"),
            (HrSubjectSnapshot, "org_id"),
            (HrSubjectSnapshot, "position_id"),
            (HrAssessmentDecisionSession, "body_org_id"),
        ):
            self.assertIsInstance(model._meta.get_field(field_name), models.BigIntegerField)

    def test_subject_snapshot_reads_effective_hr03_assignment(self):
        source = inspect.getsource(OrgAsOfResolver.resolve)
        self.assertIn("HrStaffAssignment.objects.filter", source)
        self.assertIn("employment_relationship_id__staff_id=staff_id", source)
        self.assertIn("effective_from__lte=as_of_date", source)
        self.assertIn("effective_to__gt=as_of_date", source)
        self.assertIn("org_version_as_of", source)
        self.assertNotIn("master.department_id", source)

    def test_excellent_result_is_guarded_by_published_quota(self):
        source = inspect.getsource(
            AssessmentFinalizationService._excellent_quota_blockers
        )
        self.assertIn('status="PUBLISHED"', source)
        self.assertIn("tenant_id=self.tenant_id", source)
        self.assertIn("select_for_update", source)
        self.assertIn("ASSESSMENT_EXCELLENT_QUOTA_EXCEEDED", source)
        finalize_source = inspect.getsource(AssessmentFinalizationService.finalize)
        self.assertIn("_excellent_quota_blockers", finalize_source)

    def test_browser_cannot_choose_formal_grade(self):
        repository = Path(__file__).resolve().parents[3]
        script = (
            repository / "frontend/static/hr/js/pages/hr12-assessment.js"
        ).read_text(encoding="utf-8")
        self.assertNotIn("data-annual-grade", script)
        self.assertNotIn("gradeCode, decisionSessionId", script)
        self.assertIn("档次由已提交评分和已发布规则自动计算", script)

    def test_policy_setup_creates_and_freezes_complete_result_authority(self):
        create_policy_source = inspect.getsource(views_policy.create_policy_version)
        self.assertIn("HrResultRuleVersion.objects.create", create_policy_source)
        self.assertIn("HrExcellentQuotaPolicy.objects.create", create_policy_source)
        self.assertIn("result_rule_version_id=result_rule.id", create_policy_source)
        self.assertIn("excellent_quota_policy_id=quota_policy.id", create_policy_source)

        repository = Path(__file__).resolve().parents[3]
        cycle_source = (
            repository / "backend/hr_assessment/api/views_assessment.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"scoreAggregation": "AVERAGE"', cycle_source)
        self.assertIn('"scoreToGradeMapping": result_rule.score_to_grade_mapping', cycle_source)
        self.assertIn('"maxExcellentRatio": str(quota_policy.max_excellent_ratio)', cycle_source)

    def test_session_policy_writes_are_not_csrf_exempt(self):
        source = inspect.getsource(views_policy)
        self.assertNotIn("csrf_exempt", source)

    def test_each_published_authority_has_its_own_immutable_content_seal(self):
        save_source = inspect.getsource(VersionedModel.save)
        hash_source = inspect.getsource(calculate_version_content_hash)
        self.assertIn("HR12_PUBLISHED_AUTHORITY_IMMUTABLE", save_source)
        self.assertIn("sort_keys=True", hash_source)
        finalization = inspect.getsource(AssessmentFinalizationService)
        self.assertIn("calculate_version_content_hash(result_rule)", finalization)
        self.assertIn("calculate_version_content_hash(policy)", finalization)
        policy_source = inspect.getsource(views_policy.create_policy_version)
        self.assertNotIn("authority_hash", policy_source)

    def test_result_lifecycle_workbench_matches_chinese_process(self):
        repository = Path(__file__).resolve().parents[3]
        script = (
            repository / "frontend/static/hr/js/pages/hr12-assessment.js"
        ).read_text(encoding="utf-8")
        for label in (
            "生成结果告知单",
            "确认本人意见",
            "提交结果异议",
            "复核结案",
            "正式归档",
        ):
            self.assertIn(label, script)
