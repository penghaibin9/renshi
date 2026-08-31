"""HR12 — S3 补齐: org-as-of resolver + Reviewer baseline + AMBIGUOUS_POLICY 检测。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from hr_assessment.models.cycle import HrAssessmentCycle


@dataclass
class SubjectAsOfSnapshot:
    staff_id: uuid.UUID
    org_id: Optional[uuid.UUID] = None
    org_name: str = ""
    position_id: Optional[uuid.UUID] = None
    position_name: str = ""
    job_category: str = ""
    teacher_type: str = ""
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
        try:
            from hr_staff.models.staff import HrStaffMaster
            master = HrStaffMaster.objects.filter(
                tenant_id=tenant_id, id=staff_id,
            ).select_related("person").first()
            if not master:
                return SubjectAsOfSnapshot(staff_id=staff_id, as_of_date=as_of)
            return SubjectAsOfSnapshot(
                staff_id=staff_id,
                org_id=master.department_id,
                org_name=master.get_department() or "",
                position_id=master.position_id,
                position_name=master.get_job_position() or "",
                job_category=master.worker_category or "",
                as_of_date=as_of,
            )
        except ImportError:
            return SubjectAsOfSnapshot(staff_id=staff_id, as_of_date=as_of)

    def build_reviewer_baseline(
        self, tenant_id: int, case_id: uuid.UUID, staff_id: uuid.UUID, as_of: str,
    ) -> ReviewerBaseline:
        """从 HR03 的主管/组织关系构建评审人基线。"""
        try:
            from hr_staff.models.staff import HrStaffMaster
            master = HrStaffMaster.objects.filter(
                tenant_id=tenant_id, id=staff_id,
            ).first()
            if not master:
                return ReviewerBaseline(case_id=case_id, staff_id=staff_id)
            manager_id = None
            if hasattr(master, "reporting_manager_id") and master.reporting_manager_id:
                manager_id = master.reporting_manager_id
            return ReviewerBaseline(
                case_id=case_id, staff_id=staff_id,
                direct_manager_id=manager_id,
            )
        except ImportError:
            return ReviewerBaseline(case_id=case_id, staff_id=staff_id)


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
