"""HR12 Assessment — Test Factories（生产级）。模拟 hr_staff 的函数工厂模式。"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from hr_assessment.models.policy import (
    HrAssessmentPolicyPack,
    HrAssessmentPolicyVersion,
)
from hr_assessment.models.cycle import HrAssessmentCycle
from hr_assessment.models.case import HrAssessmentCase, HrSubjectSnapshot
from hr_assessment.models.result import HrFinalAssessmentResult
from hr_assessment.models.evidence import HrSelfAssessment, HrReviewerAssignment, HrReviewerEvaluation


def make_policy_pack(
    tenant_id: int,
    code: str = "TEST-POLICY",
    name: str = "测试考核政策",
    assessment_domain: str = "ANNUAL",
) -> HrAssessmentPolicyPack:
    return HrAssessmentPolicyPack.objects.create(
        tenant_id=tenant_id, code=code, name=name, assessment_domain=assessment_domain,
    )


def make_policy_version(
    tenant_id: int,
    policy_pack: HrAssessmentPolicyPack,
    version_no: int = 1,
    status: str = "PUBLISHED",
    effective_from: date = date(2026, 1, 1),
) -> HrAssessmentPolicyVersion:
    return HrAssessmentPolicyVersion.objects.create(
        tenant_id=tenant_id,
        version_no=version_no, policy_pack=policy_pack,
        effective_from=effective_from, status=status,
        assessment_types=["ANNUAL"],
        rating_scale_version_id=uuid.uuid4(),
        indicator_set_version_id=uuid.uuid4(),
        workflow_version_id=uuid.uuid4(),
    )


def make_cycle(
    tenant_id: int,
    policy_version: HrAssessmentPolicyVersion,
    cycle_no: str = "2026-ANNUAL-01",
    assessment_type: str = "ANNUAL",
) -> HrAssessmentCycle:
    return HrAssessmentCycle.objects.create(
        tenant_id=tenant_id,
        cycle_no=cycle_no, assessment_type=assessment_type,
        name=f"测试周期 {cycle_no}",
        start_at=datetime(2026, 1, 1, 0, 0),
        end_at=datetime(2026, 12, 31, 23, 59),
        policy_version_id=policy_version.id,
    )


def make_case(
    tenant_id: int,
    cycle: HrAssessmentCycle,
    staff_id: Optional[uuid.UUID] = None,
    assessment_type: str = "ANNUAL",
    status: str = "DRAFT",
) -> HrAssessmentCase:
    return HrAssessmentCase.objects.create(
        tenant_id=tenant_id, assessment_type=assessment_type,
        cycle=cycle, staff_id=staff_id or uuid.uuid4(),
        status=status,
    )


def make_subject_snapshot(
    tenant_id: int,
    case_id: uuid.UUID,
    staff_id: uuid.UUID,
    display_name: str = "测试教师",
    org_name: str = "测试学院",
) -> HrSubjectSnapshot:
    return HrSubjectSnapshot.objects.create(
        tenant_id=tenant_id, case_id=case_id, staff_id=staff_id,
        display_name=display_name, org_name=org_name,
        snapshot_at=datetime(2026, 1, 1, 0, 0),
    )


def make_self_assessment(
    tenant_id: int,
    case_id: uuid.UUID,
    summary: str = "年度表现总结",
) -> HrSelfAssessment:
    return HrSelfAssessment.objects.create(
        tenant_id=tenant_id, case_id=case_id, summary=summary,
        submitted_at=datetime(2026, 6, 15, 10, 0),
    )


def make_reviewer_assignment(
    tenant_id: int,
    case_id: uuid.UUID,
    reviewer_role: str = "DIRECT_MANAGER",
    reviewer_staff_id: Optional[uuid.UUID] = None,
) -> HrReviewerAssignment:
    return HrReviewerAssignment.objects.create(
        tenant_id=tenant_id, case_id=case_id,
        reviewer_role=reviewer_role,
        reviewer_staff_id=reviewer_staff_id or uuid.uuid4(),
    )


def make_reviewer_evaluation(
    tenant_id: int,
    assignment: HrReviewerAssignment,
    recommendation: str = "QUALIFIED",
    indicator_scores: Optional[list] = None,
) -> HrReviewerEvaluation:
    return HrReviewerEvaluation.objects.create(
        tenant_id=tenant_id, assignment=assignment,
        indicator_evaluations_json=indicator_scores or [],
        recommendation=recommendation,
        submitted_at=datetime(2026, 7, 1, 10, 0),
    )


def make_final_result(
    tenant_id: int,
    case_id: Optional[uuid.UUID] = None,
    assessment_type: str = "ANNUAL",
    grade_code: str = "QUALIFIED",
    result_version_no: int = 1,
    status: str = "FINALIZED",
) -> HrFinalAssessmentResult:
    return HrFinalAssessmentResult.objects.create(
        tenant_id=tenant_id, case_id=case_id or uuid.uuid4(),
        assessment_type=assessment_type, grade_code=grade_code,
        result_version_no=result_version_no, status=status,
        finalized_at=datetime(2026, 8, 1, 10, 0),
    )
