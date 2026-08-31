"""
hr_staff/policies —— HR03 字段治理策略（S1 静态版；S9 升级为 HrFieldGovernancePolicy 模型）。

对齐总册 §15.2 FieldGovernancePolicy：
- field_code / edit_mode / required_permission / required_evidence / approval_policy / sensitivity_level / retroactive_allowed
V1 先用静态注册表落地约束；S9 增加可配置模型 + 更正流程校验。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from hr_staff.constants import (
    CorrectionEditMode,
    SensitivityLevel,
)


@dataclass(frozen=True)
class FieldPolicy:
    field_code: str
    edit_mode: str  # CorrectionEditMode
    sensitivity_level: str = SensitivityLevel.PUBLIC_HR
    required_permission: str = ""
    required_evidence: bool = False
    approval_policy: str = ""  # "NONE" / "HR_REVIEW" / "HR_DIRECTOR_APPROVAL"
    retroactive_allowed: bool = False

    @property
    def business_process_only(self) -> bool:
        return self.edit_mode == CorrectionEditMode.BUSINESS_PROCESS_ONLY


# ---------------------------------------------------------------------------
# V1 静态字段治理注册表（S9 前唯一事实源；S9 后与模型合并）
# ---------------------------------------------------------------------------
FIELD_GOVERNANCE_REGISTRY: dict[str, FieldPolicy] = {
    # ---- 基本身份（Person 层）----
    "person.legal_name": FieldPolicy(
        field_code="person.legal_name",
        edit_mode=CorrectionEditMode.HR_APPROVAL,
        sensitivity_level=SensitivityLevel.PUBLIC_HR,
        required_permission="hr.staff.edit_basic",
        required_evidence=False,
        approval_policy="HR_REVIEW",
    ),
    "person.preferred_name": FieldPolicy(
        field_code="person.preferred_name",
        edit_mode=CorrectionEditMode.HR_DIRECT,
        sensitivity_level=SensitivityLevel.PUBLIC_HR,
        required_permission="hr.staff.edit_basic",
    ),
    "person.gender_code": FieldPolicy(
        field_code="person.gender_code",
        edit_mode=CorrectionEditMode.SELF_REQUEST,
        sensitivity_level=SensitivityLevel.SENSITIVE,
        required_permission="hr.staff.edit_basic",
    ),
    "person.birth_date": FieldPolicy(
        field_code="person.birth_date",
        edit_mode=CorrectionEditMode.HR_APPROVAL,
        sensitivity_level=SensitivityLevel.SENSITIVE,
        required_evidence=True,
        approval_policy="HR_REVIEW",
        retroactive_allowed=False,
    ),
    # ---- 身份证明（HIGH_SENSITIVE，绝不直改）----
    "identity.document_number": FieldPolicy(
        field_code="identity.document_number",
        edit_mode=CorrectionEditMode.HR_APPROVAL,
        sensitivity_level=SensitivityLevel.HIGH_SENSITIVE,
        required_permission="hr.staff.reveal_high_sensitive",
        required_evidence=True,
        approval_policy="HR_DIRECTOR_APPROVAL",
        retroactive_allowed=False,
    ),
    # ---- 联系方式 ----
    "contact.mobile": FieldPolicy(
        field_code="contact.mobile",
        edit_mode=CorrectionEditMode.SELF_DIRECT,
        sensitivity_level=SensitivityLevel.RESTRICTED_HR,
    ),
    "contact.personal_email": FieldPolicy(
        field_code="contact.personal_email",
        edit_mode=CorrectionEditMode.SELF_DIRECT,
        sensitivity_level=SensitivityLevel.RESTRICTED_HR,
    ),
    "contact.work_email": FieldPolicy(
        field_code="contact.work_email",
        edit_mode=CorrectionEditMode.HR_DIRECT,
        sensitivity_level=SensitivityLevel.RESTRICTED_HR,
        required_permission="hr.staff.edit_basic",
    ),
    "contact.work_phone": FieldPolicy(
        field_code="contact.work_phone",
        edit_mode=CorrectionEditMode.HR_DIRECT,
        sensitivity_level=SensitivityLevel.RESTRICTED_HR,
        required_permission="hr.staff.edit_basic",
    ),
    # ---- StaffMaster ----
    "staff.staff_no": FieldPolicy(
        field_code="staff.staff_no",
        edit_mode=CorrectionEditMode.HR_APPROVAL,
        sensitivity_level=SensitivityLevel.PUBLIC_HR,
        required_permission="hr.staff.edit_basic",
        required_evidence=True,
        approval_policy="HR_DIRECTOR_APPROVAL",
        retroactive_allowed=True,
    ),
    "staff.staff_category_code": FieldPolicy(
        field_code="staff.staff_category_code",
        edit_mode=CorrectionEditMode.HR_APPROVAL,
        sensitivity_level=SensitivityLevel.PUBLIC_HR,
        required_permission="hr.staff.edit_basic",
        approval_policy="HR_REVIEW",
        retroactive_allowed=True,
    ),
    # ---- 关系/任职（BUSINESS_PROCESS_ONLY，禁止更正绕过）----
    "employment.relationship_type": FieldPolicy(
        field_code="employment.relationship_type",
        edit_mode=CorrectionEditMode.BUSINESS_PROCESS_ONLY,
        sensitivity_level=SensitivityLevel.PUBLIC_HR,
    ),
    "employment.effective_from": FieldPolicy(
        field_code="employment.effective_from",
        edit_mode=CorrectionEditMode.BUSINESS_PROCESS_ONLY,
        sensitivity_level=SensitivityLevel.PUBLIC_HR,
    ),
    "assignment.organization": FieldPolicy(
        field_code="assignment.organization",
        edit_mode=CorrectionEditMode.BUSINESS_PROCESS_ONLY,
        sensitivity_level=SensitivityLevel.PUBLIC_HR,
    ),
    "assignment.position": FieldPolicy(
        field_code="assignment.position",
        edit_mode=CorrectionEditMode.BUSINESS_PROCESS_ONLY,
        sensitivity_level=SensitivityLevel.PUBLIC_HR,
    ),
    "assignment.assignment_type": FieldPolicy(
        field_code="assignment.assignment_type",
        edit_mode=CorrectionEditMode.BUSINESS_PROCESS_ONLY,
        sensitivity_level=SensitivityLevel.PUBLIC_HR,
    ),
    "staff.employment_status": FieldPolicy(
        field_code="staff.employment_status",
        edit_mode=CorrectionEditMode.BUSINESS_PROCESS_ONLY,
        sensitivity_level=SensitivityLevel.PUBLIC_HR,
    ),
    # ---- 背景事实 ----
    "background.education": FieldPolicy(
        field_code="background.education",
        edit_mode=CorrectionEditMode.HR_DIRECT,
        sensitivity_level=SensitivityLevel.PUBLIC_HR,
        required_permission="hr.staff.background.manage",
        required_evidence=True,
        approval_policy="HR_REVIEW",
    ),
    "background.credential": FieldPolicy(
        field_code="background.credential",
        edit_mode=CorrectionEditMode.HR_DIRECT,
        sensitivity_level=SensitivityLevel.RESTRICTED_HR,
        required_permission="hr.staff.background.manage",
        required_evidence=True,
    ),
}


def get_field_policy(field_code: str) -> Optional[FieldPolicy]:
    return FIELD_GOVERNANCE_REGISTRY.get(field_code)
