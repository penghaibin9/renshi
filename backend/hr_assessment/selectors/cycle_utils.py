"""HR12 — S3 补齐: org-as-of resolver + Reviewer baseline + AMBIGUOUS_POLICY 检测。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from django.db.models import Q
from django.utils.dateparse import parse_date

from hr_assessment.models.cycle import HrAssessmentCycle


@dataclass
class SubjectAsOfSnapshot:
    staff_id: uuid.UUID
    employment_relationship_id: Optional[uuid.UUID] = None
    primary_assignment_id: Optional[uuid.UUID] = None
    org_id: Optional[int] = None
    org_name: str = ""
    position_id: Optional[int] = None
    position_name: str = ""
    job_category: str = ""
    teacher_type: str = ""
    direct_manager_id: Optional[uuid.UUID] = None
    as_of_date: str = ""


@dataclass
class ReviewerBaseline:
    case_id: uuid.UUID
    staff_id: uuid.UUID
    direct_manager_id: Optional[uuid.UUID] = None
    org_head_ids: List[uuid.UUID] = field(default_factory=list)
    peer_ids: List[uuid.UUID] = field(default_factory=list)


class OrgAsOfResolver:
    """从 HR03 解析 as-of 时的组织/岗位/评审线快照。"""

    def resolve(self, tenant_id: int, staff_id: uuid.UUID, as_of: str) -> SubjectAsOfSnapshot:
        from hr_staff.models import HrStaffAssignment, HrStaffMaster
        from hr_structure.selectors.effective import org_version_as_of

        as_of_date = as_of if isinstance(as_of, date) else parse_date(str(as_of))
        if as_of_date is None:
            raise ValueError("ASSESSMENT_SUBJECT_AS_OF_INVALID")
        master = HrStaffMaster.objects.filter(
            tenant_id=tenant_id,
            id=staff_id,
        ).first()
        if master is None:
            raise ValueError("ASSESSMENT_SUBJECT_STAFF_NOT_FOUND")
        assignments = list(
            HrStaffAssignment.objects.filter(
                tenant_id=tenant_id,
                employment_relationship_id__staff_id=staff_id,
                assignment_type="PRIMARY",
                status="ACTIVE",
                effective_from__lte=as_of_date,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of_date))
            .select_related(
                "organization_id",
                "position_id__post_catalog_version_id",
                "reporting_staff_id",
            )
            .order_by("-effective_from", "-version", "id")[:2]
        )
        if len(assignments) > 1:
            raise ValueError("ASSESSMENT_SUBJECT_PRIMARY_ASSIGNMENT_AMBIGUOUS")
        assignment = assignments[0] if assignments else None
        organization_id = assignment.organization_id_id if assignment else None
        position_id = assignment.position_id_id if assignment else None
        organization = (
            org_version_as_of(tenant_id, organization_id, as_of_date)
            if organization_id
            else None
        )
        position = assignment.position_id if assignment else None
        post_catalog = position.post_catalog_version_id if position else None
        return SubjectAsOfSnapshot(
            staff_id=staff_id,
            employment_relationship_id=(
                assignment.employment_relationship_id_id if assignment else None
            ),
            primary_assignment_id=assignment.id if assignment else None,
            org_id=organization_id,
            org_name=organization.name if organization else "",
            position_id=position_id,
            position_name=post_catalog.name if post_catalog else "",
            job_category=post_catalog.category if post_catalog else "",
            teacher_type=master.staff_category_code,
            direct_manager_id=(
                assignment.reporting_staff_id_id if assignment else None
            ),
            as_of_date=as_of_date.isoformat(),
        )

    def build_reviewer_baseline(
        self, tenant_id: int, case_id: uuid.UUID, staff_id: uuid.UUID, as_of: str,
    ) -> ReviewerBaseline:
        """从 HR03 的主管/组织关系构建评审人基线。"""
        from hr_staff.models import HrStaffAssignment

        as_of_date = as_of if isinstance(as_of, date) else parse_date(str(as_of))
        if as_of_date is None:
            raise ValueError("ASSESSMENT_REVIEWER_AS_OF_INVALID")
        assignment = (
            HrStaffAssignment.objects.filter(
                tenant_id=tenant_id,
                employment_relationship_id__staff_id=staff_id,
                assignment_type="PRIMARY",
                status="ACTIVE",
                effective_from__lte=as_of_date,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of_date))
            .order_by("-effective_from", "-version", "id")
            .first()
        )
        return ReviewerBaseline(
            case_id=case_id,
            staff_id=staff_id,
            direct_manager_id=(
                assignment.reporting_staff_id_id if assignment else None
            ),
        )


class AmbiguousPolicyDetector:
    """多套已发布政策冲突检测 — AMBIGUOUS_POLICY fail-closed。"""

    def detect(self, tenant_id: int, as_of: str, assessment_type: str) -> Optional[List[Dict]]:
        from hr_assessment.models.policy import HrAssessmentPolicyVersion

        versions = HrAssessmentPolicyVersion.objects.filter(
            tenant_id=tenant_id, status="PUBLISHED",
            effective_from__lte=as_of, assessment_types__contains=[assessment_type],
        ).exclude(effective_to__lt=as_of).order_by("-version_no")

        unique_packs = {v.policy_pack_id for v in versions}
        if len(unique_packs) > 1:
            return [
                {"policy_pack_id": str(v.policy_pack_id), "version_no": v.version_no, "code": v.policy_pack.code}
                for v in versions if v.policy_pack_id in unique_packs
            ]
        return None
