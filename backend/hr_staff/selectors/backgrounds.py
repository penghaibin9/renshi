"""
hr_staff/selectors/backgrounds.py —— HR03-04 教育资格履历查询（S7，只读）。

数据质量状态（总册 §13.8）：COMPLETE / OPTIONAL_MISSING / REQUIRED_MISSING / CONFLICT / UNVERIFIED / EXPIRED。
"""

from __future__ import annotations

from datetime import date

from hr_staff.context import HrStaffRequestContext
from hr_staff.models import (
    HrCredential,
    HrDegreeRecord,
    HrEducationExperience,
    HrTalentHonor,
    HrWorkExperience,
)
from hr_staff.policies.scope_policy import StaffNotFound


class BackgroundSelector:
    def __init__(self, context: HrStaffRequestContext):
        self.context = context
        self.tenant_id = context.tenant_id

    def _deny_check(self, staff_id):
        """P1-5：读路径强制 data scope（tenant + scope + fail-closed）。"""
        from hr_staff.policies.scope_policy import ScopeEnforcer

        return ScopeEnforcer(self.context).get_staff_or_deny(staff_id)

    def bundle(self, staff_id) -> dict:
        self._deny_check(staff_id)  # P1-5
        return {
            "education": [self._edu(e) for e in HrEducationExperience.objects.filter(
                tenant_id=self.tenant_id, staff_id=staff_id
            ).order_by("-end_date")],
            "degrees": [self._degree(d) for d in HrDegreeRecord.objects.filter(
                tenant_id=self.tenant_id, staff_id=staff_id
            ).order_by("-awarded_date")],
            "workExperience": [self._work(w) for w in HrWorkExperience.objects.filter(
                tenant_id=self.tenant_id, staff_id=staff_id
            ).order_by("-start_date")],
            "credentials": [self._credential(c) for c in HrCredential.objects.filter(
                tenant_id=self.tenant_id, staff_id=staff_id
            ).order_by("-issue_date")],
            "talentHonors": [self._honor(h) for h in HrTalentHonor.objects.filter(
                tenant_id=self.tenant_id, staff_id=staff_id
            ).order_by("-awarded_date")],
        }

    @staticmethod
    def _edu(e: HrEducationExperience) -> dict:
        return {
            "id": str(e.id),
            "schoolName": e.school_name,
            "countryRegion": e.country_region,
            "educationLevel": e.education_level,
            "majorName": e.major_name,
            "studyType": e.study_type,
            "startDate": e.start_date.isoformat() if e.start_date else None,
            "endDate": e.end_date.isoformat() if e.end_date else None,
            "isHighestEducation": e.is_highest_education,
            "verificationStatus": e.verification_status,
        }

    @staticmethod
    def _degree(d: HrDegreeRecord) -> dict:
        return {
            "id": str(d.id),
            "degreeLevel": d.degree_level,
            "degreeName": d.degree_name,
            "grantingInstitution": d.granting_institution,
            "major": d.major,
            "awardedDate": d.awarded_date.isoformat() if d.awarded_date else None,
            "verificationStatus": d.verification_status,
        }

    @staticmethod
    def _work(w: HrWorkExperience) -> dict:
        return {
            "id": str(w.id),
            "organizationName": w.organization_name,
            "departmentName": w.department_name,
            "positionTitle": w.position_title,
            "experienceType": w.experience_type,
            "startDate": w.start_date.isoformat() if w.start_date else None,
            "endDate": w.end_date.isoformat() if w.end_date else None,
            "verificationStatus": w.verification_status,
        }

    @staticmethod
    def _credential(c: HrCredential) -> dict:
        return {
            "id": str(c.id),
            "credentialType": c.credential_type,
            "credentialName": c.credential_name,
            "credentialNoMasked": c.credential_no_masked,
            "issuingAuthority": c.issuing_authority,
            "issueDate": c.issue_date.isoformat() if c.issue_date else None,
            "expiryDate": c.expiry_date.isoformat() if c.expiry_date else None,
            "level": c.level,
            "status": c.status,
            "verificationStatus": c.verification_status,
        }

    @staticmethod
    def _honor(h: HrTalentHonor) -> dict:
        return {
            "id": str(h.id),
            "honorName": h.honor_name,
            "honorType": h.honor_type,
            "grantingAuthority": h.granting_authority,
            "awardedDate": h.awarded_date.isoformat() if h.awarded_date else None,
            "verificationStatus": h.verification_status,
        }
