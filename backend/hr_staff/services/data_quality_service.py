"""
hr_staff/services/data_quality_service.py —— 数据质量与异常中心（总册 §34，补接线）。

异常类型：MISSING_REQUIRED / DUPLICATE_PERSON / ORPHAN_LEGACY_REFERENCE /
ORG_MAPPING_MISSING / POSITION_MAPPING_MISSING / ASSIGNMENT_OVERLAP /
PRIMARY_ASSIGNMENT_MISSING / STAFF_NO_CONFLICT / IDENTITY_CONFLICT /
CREDENTIAL_EXPIRED / MATERIAL_MISSING / UNVERIFIED_HIGH_VALUE_FACT / LEGACY_AUTHORITY_MISMATCH。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.utils import timezone

from hr_staff.models import (
    HrCredential,
    HrEmploymentRelationship,
    HrPerson,
    HrStaffAssignment,
    HrStaffMaster,
)
from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService


RECONCILIATION_LABELS = {
    "STAFF_NO_MISMATCH": "工号",
    "DATE_JOINING_MISMATCH": "首次入职日期",
    "DEPARTMENT_MISMATCH": "当前部门",
    "POSITION_MISMATCH": "当前岗位",
    "STATUS_MISMATCH": "在职状态",
}


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
        self.as_of = as_of or timezone.localdate()
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

        # ---- 补充 8 类规则（§34 全 13 类）----

        # ASSIGNMENT_OVERLAP：PRIMARY 段重叠（同关系有界段重叠）
        from django.db.models import Q

        primary_assignments = list(
            HrStaffAssignment.objects.filter(
                tenant_id=self.tenant_id,
                employment_relationship_id__staff_id=staff,
                assignment_type="PRIMARY",
            ).order_by("effective_from")
        )
        for i in range(len(primary_assignments) - 1):
            a, b = primary_assignments[i], primary_assignments[i + 1]
            if a.effective_to and b.effective_from and a.effective_to > b.effective_from:
                issues.append(DataQualityIssue(staff_id, staff_no, "ASSIGNMENT_OVERLAP", "HIGH",
                                               f"PRIMARY 任职段 {a.effective_from}~{a.effective_to} 与 {b.effective_from} 重叠"))
                break

        # STAFF_NO_CONFLICT：工号缺失
        if not staff.staff_no:
            issues.append(DataQualityIssue(staff_id, staff_no or "?", "STAFF_NO_CONFLICT", "HIGH", "工号缺失"))

        # IDENTITY_CONFLICT：同 tenant 同证件 fingerprint 多 Person
        from hr_staff.models import HrPersonIdentityDocument

        fp = (HrPersonIdentityDocument.objects.filter(tenant_id=self.tenant_id, person_id=staff.person_id)
              .exclude(document_number_fingerprint="").values("document_number_fingerprint").first())
        if fp:
            count = HrPersonIdentityDocument.objects.filter(
                tenant_id=self.tenant_id, document_number_fingerprint=fp["document_number_fingerprint"]
            ).count()
            if count > 1:
                issues.append(DataQualityIssue(staff_id, staff_no, "IDENTITY_CONFLICT", "MEDIUM",
                                               f"同证件 fingerprint 归属 {count} 个 Person"))

        # DUPLICATE_PERSON：同 tenant 同姓名+出生日期的 Person
        if staff.person_id.birth_date:
            dup_count = (
                HrPerson.objects.filter(
                    tenant_id=self.tenant_id,
                    legal_name__iexact=staff.person_id.legal_name,
                    birth_date=staff.person_id.birth_date,
                ).count()
                - 1
            )
            if dup_count > 0:
                issues.append(DataQualityIssue(staff_id, staff_no, "DUPLICATE_PERSON", "LOW",
                                               f"存在 {dup_count} 个疑似重复 Person（同姓名+生日）"))

        # POSITION_MAPPING_MISSING：任职有组织但无岗位
        has_org_no_pos = HrStaffAssignment.objects.filter(
            tenant_id=self.tenant_id,
            employment_relationship_id__staff_id=staff,
            organization_id__isnull=False,
            position_id__isnull=True,
        ).exists()
        if has_org_no_pos:
            issues.append(DataQualityIssue(staff_id, staff_no, "POSITION_MAPPING_MISSING", "LOW",
                                           "有组织但无权威岗位"))

        # MATERIAL_MISSING：有教育记录但无对应学历材料
        from hr_staff.models import HrEducationExperience, HrStaffMaterial

        has_edu = HrEducationExperience.objects.filter(tenant_id=self.tenant_id, staff_id=staff).exists()
        has_edu_mat = HrStaffMaterial.objects.filter(
            tenant_id=self.tenant_id, staff_id=staff, category_code="EDUCATION"
        ).exists()
        if has_edu and not has_edu_mat:
            issues.append(DataQualityIssue(staff_id, staff_no, "MATERIAL_MISSING", "LOW", "有教育经历但无学历材料"))

        # 旧系统映射与权威数据对账：只报告真实差异，不以“建议核对”冒充异常。
        if staff.legacy_employee_id:
            from hr_staff.legacy.reconciliation import ReconciliationService

            result = ReconciliationService(
                self.tenant_id,
                as_of=self.as_of,
            ).reconcile_staff(staff)
            if "LEGACY_LINK_MISSING" in result.mismatches:
                issues.append(DataQualityIssue(
                    staff_id,
                    staff_no,
                    "ORPHAN_LEGACY_REFERENCE",
                    "LOW",
                    "旧系统人员映射已失效或不属于当前学校",
                ))
            else:
                mismatch_labels = [
                    RECONCILIATION_LABELS[code]
                    for code in result.mismatches
                    if code in RECONCILIATION_LABELS
                ]
                if mismatch_labels:
                    issues.append(DataQualityIssue(
                        staff_id,
                        staff_no,
                        "LEGACY_AUTHORITY_MISMATCH",
                        "LOW",
                        "新旧数据不一致：" + "、".join(mismatch_labels),
                    ))
        return issues
