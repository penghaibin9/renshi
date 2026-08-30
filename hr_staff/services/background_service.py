"""
hr_staff/services/background_service.py —— 教育/资格背景事实服务（S7）。

规则：
- 写入按 FieldGovernancePolicy 判定（policies.FIELD_GOVERNANCE_REGISTRY）；
- 最高学历不靠"最后一条"：设置 is_highest_education 时校验唯一；
- 时间校验由 DB CheckConstraint 兜底；
- evidence_material_id 由 S8 材料档案回填。
"""

from __future__ import annotations

from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_staff.constants import SourceCategory, VerificationStatus
from hr_staff.models import (
    HrCredential,
    HrDegreeRecord,
    HrEducationExperience,
    HrTalentHonor,
    HrWorkExperience,
)
from hr_staff.policies import get_field_policy
from hr_staff.services.audit_service import write_audit_event
from hr_staff.services.common import resolve_staff


class BackgroundPolicyDenied(Exception):
    code = "CORRECTION_POLICY_DENIED"


class BackgroundService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None, *, has_manage_perm=False):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id
        self.has_manage_perm = has_manage_perm

    def _assert_policy(self, field_code):
        policy = get_field_policy(field_code)
        if policy is None:
            raise BackgroundPolicyDenied(f"字段未登记治理策略: {field_code}")
        if policy.required_permission and not self.has_manage_perm:
            raise BackgroundPolicyDenied(f"缺少权限 {policy.required_permission}")

    # ---------------- 教育经历 ----------------
    @transaction.atomic
    def add_education(
        self,
        *,
        staff_id,
        school_name: str,
        education_level: str,
        major_name: str = "",
        country_region: str = "CN",
        study_type: str = "",
        start_date=None,
        end_date=None,
        is_highest_education: bool = False,
        verification_status: str = VerificationStatus.UNVERIFIED,
        verified_by: int | None = None,
        verified_at=None,
        source: str = SourceCategory.HR_ENTERED,
        source_domain: str = "",
        source_business_id: str | None = None,
    ) -> HrEducationExperience:
        self._assert_policy("background.education")
        staff = resolve_staff(self.tenant_id, staff_id)  # P1-6 跨租户防线
        if is_highest_education:
            self._clear_highest_education(staff)
        record = HrEducationExperience.objects.create(
            tenant_id=self.tenant_id,
            staff_id=staff,
            school_name=school_name,
            country_region=country_region,
            education_level=education_level,
            major_name=major_name,
            study_type=study_type,
            start_date=start_date,
            end_date=end_date,
            is_highest_education=is_highest_education,
            verification_status=verification_status,
            verified_by=verified_by,
            verified_at=verified_at or (
                timezone.now() if verification_status == VerificationStatus.VERIFIED else None
            ),
            source=source,
            source_domain=source_domain,
            source_business_id=source_business_id,
        )
        write_audit_event(
            tenant_id=self.tenant_id,
            action="EducationAdded",
            actor_user_id=self.actor_user_id,
            staff_id=staff.id,
        )
        return record

    def _clear_highest_education(self, staff):
        HrEducationExperience.objects.filter(
            tenant_id=self.tenant_id, staff_id=staff, is_highest_education=True
        ).update(is_highest_education=False)

    # ---------------- 学位 ----------------
    @transaction.atomic
    def add_degree(
        self,
        *,
        staff_id,
        degree_level: str,
        degree_name="",
        granting_institution="",
        major="",
        awarded_date=None,
        verification_status: str = VerificationStatus.UNVERIFIED,
        verified_by: int | None = None,
        verified_at=None,
        source: str = SourceCategory.HR_ENTERED,
        source_domain: str = "",
        source_business_id: str | None = None,
    ) -> HrDegreeRecord:
        self._assert_policy("background.education")
        staff = resolve_staff(self.tenant_id, staff_id)  # P1-6
        record = HrDegreeRecord.objects.create(
            tenant_id=self.tenant_id,
            staff_id=staff,
            degree_level=degree_level,
            degree_name=degree_name,
            granting_institution=granting_institution,
            major=major,
            awarded_date=awarded_date,
            verification_status=verification_status,
            verified_by=verified_by,
            verified_at=verified_at or (
                timezone.now() if verification_status == VerificationStatus.VERIFIED else None
            ),
            source=source,
            source_domain=source_domain,
            source_business_id=source_business_id,
        )
        write_audit_event(
            tenant_id=self.tenant_id,
            action="DegreeAdded",
            actor_user_id=self.actor_user_id,
            staff_id=staff.id,
        )
        return record

    # ---------------- 工作经历 ----------------
    @transaction.atomic
    def add_work_experience(
        self, *, staff_id, organization_name: str, department_name="", position_title="", experience_type="UNIVERSITY", start_date=None, end_date=None
    ) -> HrWorkExperience:
        self._assert_policy("background.education")
        staff = resolve_staff(self.tenant_id, staff_id)  # P1-6
        record = HrWorkExperience.objects.create(
            tenant_id=self.tenant_id,
            staff_id=staff,
            organization_name=organization_name,
            department_name=department_name,
            position_title=position_title,
            experience_type=experience_type,
            start_date=start_date,
            end_date=end_date,
            source=SourceCategory.HR_ENTERED,
        )
        write_audit_event(
            tenant_id=self.tenant_id,
            action="WorkExperienceAdded",
            actor_user_id=self.actor_user_id,
            staff_id=staff.id,
        )
        return record

    # ---------------- 资格/证书 ----------------
    @transaction.atomic
    def add_credential(
        self,
        *,
        staff_id,
        credential_type: str,
        credential_name: str,
        credential_no: str = "",
        issuing_authority: str = "",
        issue_date=None,
        expiry_date=None,
        level: str = "",
        source_domain: str = "",
        source_business_id: str = "",
        verification_status: str = VerificationStatus.UNVERIFIED,
        verified_by: int | None = None,
        verified_at=None,
        source: str = SourceCategory.HR_ENTERED,
    ) -> HrCredential:
        self._assert_policy("background.credential")
        staff = resolve_staff(self.tenant_id, staff_id)  # P1-6
        masked = self._mask_credential_no(credential_no)
        record = HrCredential.objects.create(
            tenant_id=self.tenant_id,
            staff_id=staff,
            credential_type=credential_type,
            credential_name=credential_name,
            credential_no_masked=masked,
            issuing_authority=issuing_authority,
            issue_date=issue_date,
            expiry_date=expiry_date,
            level=level,
            source_domain=source_domain,
            source_business_id=source_business_id,
            verification_status=verification_status,
            verified_by=verified_by,
            verified_at=verified_at or (
                timezone.now() if verification_status == VerificationStatus.VERIFIED else None
            ),
            source=source,
        )
        write_audit_event(
            tenant_id=self.tenant_id,
            action="CredentialAdded",
            actor_user_id=self.actor_user_id,
            staff_id=staff.id,
        )
        return record

    @staticmethod
    def _mask_credential_no(value: str) -> str:
        if not value:
            return ""
        if len(value) <= 6:
            return "*" * len(value)
        return f"{value[:2]}****{value[-2:]}"

    # ---------------- 人才荣誉 ----------------
    @transaction.atomic
    def add_talent_honor(self, *, staff_id, honor_name: str, honor_type="", granting_authority="", awarded_date=None) -> HrTalentHonor:
        self._assert_policy("background.credential")
        staff = resolve_staff(self.tenant_id, staff_id)  # P1-6
        record = HrTalentHonor.objects.create(
            tenant_id=self.tenant_id,
            staff_id=staff,
            honor_name=honor_name,
            honor_type=honor_type,
            granting_authority=granting_authority,
            awarded_date=awarded_date,
            source=SourceCategory.HR_ENTERED,
        )
        write_audit_event(
            tenant_id=self.tenant_id,
            action="TalentHonorAdded",
            actor_user_id=self.actor_user_id,
            staff_id=staff.id,
        )
        return record
