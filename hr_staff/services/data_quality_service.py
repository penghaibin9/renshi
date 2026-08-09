"""
hr_staff/services/data_quality_service.py —— 数据质量与异常中心（总册 §34，补接线）。

异常类型：MISSING_REQUIRED / DUPLICATE_PERSON / ORPHAN_LEGACY_REFERENCE /
ORG_MAPPING_MISSING / POSITION_MAPPING_MISSING / ASSIGNMENT_OVERLAP /
PRIMARY_ASSIGNMENT_MISSING / STAFF_NO_CONFLICT / IDENTITY_CONFLICT /
CREDENTIAL_EXPIRED / MATERIAL_MISSING / UNVERIFIED_HIGH_VALUE_FACT / LEGACY_AUTHORITY_MISMATCH。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from hr_staff.models import (
    HrCredential,
    HrEmploymentRelationship,
    HrStaffAssignment,
    HrStaffMaster,
)
from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService


@dataclass
class DataQualityIssue:
    staff_id: str
    staff_no: str
    rule: str
    severity: str  # HIGH / MEDIUM / LOW
    message: str
    detected_at: str = ""

    def to_dict(self) -> dict:
        return {
            "staffId": self.staff_id,
            "staffNo": self.staff_no,
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
            "detectedAt": self.detected_at,
        }


class DataQualityService:
    """按 tenant 扫描数据质量异常（只读）。"""

    def __init__(self, tenant_id: int, as_of: date | None = None):
        self.tenant_id = tenant_id
        self.as_of = as_of or date.today()
        self.qs = EffectiveDatedQueryService(tenant_id)

    def scan(self) -> dict:
        issues: list[DataQualityIssue] = []
        for staff in HrStaffMaster.objects.filter(tenant_id=self.tenant_id).select_related("person_id"):
            issues += self._scan_staff(staff)
        return {
            "total": len(issues),
            "issues": [i.to_dict() for i in issues],
        }

    def _scan_staff(self, staff) -> list[DataQualityIssue]:
        issues = []
        staff_id, staff_no = str(staff.id), staff.staff_no

        # PRIMARY_ASSIGNMENT_MISSING：ACTIVE 但无当前主岗
        status = self.qs.status_as_of(staff.id, self.as_of)
        primary = self.qs.primary_assignment_as_of(staff.id, self.as_of)
        if status == "ACTIVE" and primary is None:
            issues.append(
                DataQualityIssue(
                    staff_id, staff_no, "PRIMARY_ASSIGNMENT_MISSING", "HIGH",
                    "ACTIVE 但当前无主岗任职",
                )
            )

        # MISSING_REQUIRED：无任何关系段
        if not HrEmploymentRelationship.objects.filter(tenant_id=self.tenant_id, staff_id=staff).exists():
            issues.append(
                DataQualityIssue(
                    staff_id, staff_no, "MISSING_REQUIRED", "MEDIUM",
                    "无任何聘用关系记录",
                )
            )

        # ORG_MAPPING_MISSING：任职仅有 legacy 映射、无权威组织
        legacy_only = HrStaffAssignment.objects.filter(
            tenant_id=self.tenant_id,
            employment_relationship_id__staff_id=staff,
            organization_id__isnull=True,
        ).exclude(legacy_department_id__isnull=True)
        if legacy_only.exists():
            issues.append(
                DataQualityIssue(
                    staff_id, staff_no, "ORG_MAPPING_MISSING", "LOW",
                    "任职段仅 legacy 映射，未绑定 HR02 权威组织",
                )
            )

        # UNVERIFIED_HIGH_VALUE_FACT：教育/证件未核验
        if staff.person_id.identity_documents.filter(
            verification_status="UNVERIFIED"
        ).exists():
            issues.append(
                DataQualityIssue(
                    staff_id, staff_no, "UNVERIFIED_HIGH_VALUE_FACT", "MEDIUM",
                    "存在未核验的身份证明",
                )
            )

        # CREDENTIAL_EXPIRED：证书已过期
        if HrCredential.objects.filter(
            tenant_id=self.tenant_id, staff_id=staff, status="EXPIRED"
        ).exists():
            issues.append(
                DataQualityIssue(
                    staff_id, staff_no, "CREDENTIAL_EXPIRED", "MEDIUM",
                    "存在已过期证书",
                )
            )

        return issues
