"""
hr_onboarding/integrations/hr03.py

HR03 激活 Provider 契约（00 §92 / 05 §10.5-10.6）。

S0/S1 核实（2026-08-09）：HR03-S2/S3 已交付
（HrPerson/StaffMaster + PersonIdentityService/StaffMasterService +
 HrEmploymentRelationship/HrStaffAssignment + EmploymentService/AssignmentService），
本 Provider 全部真实调用，mode = HR03_READY。

硬规则：
- 不自动通过手机号/email 合并 Person（LIKELY → PERSON_MATCH_REQUIRED）；
- 同一个 HR04 ProposedHire 不得重复创建两份 onboarding case（HR05 侧 unique 兜底）；
- 不建第二份 StaffMaster（HR03 StaffMasterService canonical 唯一约束）；
- 工号由 HR03 分配，HR05 禁止 max+1；
- 转正失败走正式人事事件，不得 Employee.is_active=False（HR05-S7）。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


class Hr03ActivationProviderError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(message)


def map_relationship_type(employment_type: str) -> str:
    """employment_type → HR03 RelationshipType（05 §21 映射，字典显式）。"""
    from hr_staff.constants import RelationshipType

    mapping = {
        "FULL_TIME": RelationshipType.REGULAR_EMPLOYMENT,
        "PART_TIME": RelationshipType.OTHER,
        "EXTERNAL": RelationshipType.EXTERNAL_PART_TIME,
        "RETIRED_REHIRED": RelationshipType.RETIRED_REHIRE,
        "OTHER": RelationshipType.OTHER,
    }
    return mapping.get(employment_type, RelationshipType.OTHER)


class Hr03ActivationProvider:
    """HR05 视角的 HR03 生效适配层（全部真实调用）。"""

    mode = "HR03_READY"

    def match_or_create_person(
        self,
        *,
        tenant_id: int,
        legal_name: str,
        preferred_name: str = "",
        gender_code: Optional[str] = None,
        birth_date: Optional[date] = None,
        document_type: str = "NATIONAL_ID",
        document_number: Optional[str] = None,
        document_valid_from: Optional[date] = None,
        document_valid_to: Optional[date] = None,
        contacts: Optional[list[dict]] = None,
    ):
        """
        Person 匹配/创建（PersonIdentityService）。
        - HARD（证件指纹）→ 幂等返回既有 Person；
        - LIKELY → 抛 PersonDuplicateReviewRequired（PERSON_MATCH_REQUIRED）；
        - NO_MATCH → 创建。
        """
        from hr_staff.services.person_identity_service import (
            PersonDuplicateReviewRequired,
            PersonIdentityService,
        )

        try:
            return PersonIdentityService().create_person_with_identity(
                tenant_id=tenant_id,
                legal_name=legal_name,
                preferred_name=preferred_name,
                gender_code=gender_code,
                birth_date=birth_date,
                document_type=document_type,
                document_number=document_number,
                document_valid_from=document_valid_from,
                document_valid_to=document_valid_to,
                contacts=contacts or [],
            )
        except PersonDuplicateReviewRequired as exc:
            raise Hr03ActivationProviderError("PERSON_MATCH_REQUIRED", str(exc))
        except Exception as exc:
            raise Hr03ActivationProviderError("HR03_PERSON_CREATE_FAILED", str(exc))

    def create_staff_master(
        self,
        *,
        tenant_id: int,
        person_id,
        staff_category_code: str = "TEACHER",
        staff_no: Optional[str] = None,
        legacy_employee_id: Optional[int] = None,
    ):
        """创建 StaffMaster（StaffMasterService）。staff_no 由 HR03 分配。"""
        from hr_staff.services.staff_master_service import (
            DuplicateStaffMaster,
            StaffMasterService,
            StaffNoConflict,
        )

        try:
            return StaffMasterService().create_staff(
                tenant_id=tenant_id,
                person_id=person_id,
                staff_category_code=staff_category_code,
                staff_no=staff_no,
                legacy_employee_id=legacy_employee_id,
                source="BUSINESS_PROCESS",
            )
        except StaffNoConflict as exc:
            raise Hr03ActivationProviderError("STAFF_NUMBER_CONFLICT", str(exc))
        except DuplicateStaffMaster as exc:
            raise Hr03ActivationProviderError("DUPLICATE_STAFF_MASTER", str(exc))
        except Exception as exc:
            raise Hr03ActivationProviderError("HR03_STAFF_CREATE_FAILED", str(exc))

    def create_employment(
        self,
        *,
        tenant_id: int,
        staff_id,
        employment_type: str = "FULL_TIME",
        effective_from: date,
        source_business_id: str = "",
        reason_code: str = "ONBOARDING",
    ):
        """创建聘用关系（EmploymentService.start_relationship）。"""
        from hr_staff.policies.assignment_policy import AssignmentPolicyViolation
        from hr_staff.services.employment_service import EmploymentService

        try:
            return EmploymentService(tenant_id=tenant_id).start_relationship(
                staff_id=staff_id,
                relationship_type=map_relationship_type(employment_type),
                employment_type=employment_type,
                effective_from=effective_from,
                source_business_type="HR05_ONBOARDING",
                source_business_id=source_business_id,
                reason_code=reason_code,
            )
        except AssignmentPolicyViolation as exc:
            raise Hr03ActivationProviderError(exc.code or "ASSIGNMENT_OVERLAP", str(exc))
        except Exception as exc:
            raise Hr03ActivationProviderError("HR03_EMPLOYMENT_CREATE_FAILED", str(exc))

    def create_assignment(
        self,
        *,
        tenant_id: int,
        employment_relationship_id,
        assignment_type: str = "PRIMARY",
        effective_from: date,
        organization_id=None,
        position_id=None,
        post_catalog_id=None,
        fte: float = 1.0,
        source_business_id: str = "",
    ):
        """
        创建主岗任职（AssignmentService.create_assignment，含 HR02 capacity 校验）。

        注意：HR03 AssignmentPolicy / AssignmentService 会把权威引用作为模型实例使用，
        因此必须把上游携带的 pk 解析为同 tenant 模型实例后再传；不能把 UUID
        直接赋给命名为 employment_relationship_id 的 ForeignKey descriptor。
        """
        from decimal import Decimal

        from hr_staff.models import HrEmploymentRelationship
        from hr_staff.policies.assignment_policy import AssignmentPolicyViolation
        from hr_staff.services.assignment_service import AssignmentService
        from hr_structure.models import HrOrganization, HrPosition, HrPostCatalogVersion

        relationship = (
            employment_relationship_id
            if isinstance(employment_relationship_id, HrEmploymentRelationship)
            else HrEmploymentRelationship.objects.filter(
                tenant_id=tenant_id,
                id=employment_relationship_id,
            ).first()
        )
        if relationship is None or relationship.tenant_id != tenant_id:
            raise Hr03ActivationProviderError(
                "EMPLOYMENT_RELATIONSHIP_NOT_FOUND",
                "聘用关系不存在或不属于当前学校",
            )

        org = None
        if organization_id is not None:
            org = HrOrganization.objects.filter(tenant_id=tenant_id, id=organization_id).first()
            if org is None:
                raise Hr03ActivationProviderError("ORG_MAPPING_MISSING", "组织不存在或不属于当前学校")
        pos = None
        if position_id is not None:
            pos = HrPosition.objects.filter(tenant_id=tenant_id, id=position_id).first()
            if pos is None:
                raise Hr03ActivationProviderError("POSITION_NOT_FOUND", "岗位不存在或不属于当前学校")
        post_catalog_version = None
        if post_catalog_id is not None:
            post_catalog_version = HrPostCatalogVersion.objects.filter(id=post_catalog_id).first()
            if post_catalog_version is None:
                raise Hr03ActivationProviderError("POST_CATALOG_NOT_FOUND", "岗位目录版本不存在")

        try:
            return AssignmentService(tenant_id=tenant_id).create_assignment(
                employment_relationship_id=relationship,
                assignment_type=assignment_type,
                effective_from=effective_from,
                organization_id=org,
                position_id=pos,
                post_catalog_id=post_catalog_version,
                fte=Decimal(str(fte)),
                source_business_type="HR05_ONBOARDING",
                source_business_id=source_business_id,
            )
        except AssignmentPolicyViolation as exc:
            raise Hr03ActivationProviderError(exc.code or "ASSIGNMENT_CREATE_FAILED", str(exc))
        except Exception as exc:
            raise Hr03ActivationProviderError("HR03_ASSIGNMENT_CREATE_FAILED", str(exc))


class Hr03MockProvider(Hr03ActivationProvider):
    """
    仅用于 S4 测试的内存实现（显式 mode=MOCK）。
    严禁在生产代码路径被当作真实 HR03 生效结果。
    """

    mode = "MOCK"

    def __init__(self):
        import uuid as _uuid

        self._people = {}
        self._staff = {}
        self._uuid = _uuid

    def match_or_create_person(self, **kwargs):
        key = (kwargs["tenant_id"], kwargs["legal_name"])
        if key in self._people:
            return self._people[key]
        person = type(
            "MockPerson",
            (),
            {"id": self._uuid.uuid4(), "legal_name": kwargs["legal_name"]},
        )
        self._people[key] = person
        return person

    def create_staff_master(self, **kwargs):
        key = (kwargs["tenant_id"], kwargs["person_id"])
        if key in self._staff:
            from hr_staff.services.staff_master_service import DuplicateStaffMaster

            raise DuplicateStaffMaster("duplicate")
        staff = type(
            "MockStaff",
            (),
            {
                "id": self._uuid.uuid4(),
                "staff_no": kwargs.get("staff_no") or f"T{len(self._staff) + 1:06d}",
            },
        )
        self._staff[key] = staff
        return staff

    def create_employment(self, **kwargs):
        return type("MockEmployment", (), {"id": self._uuid.uuid4()})()

    def create_assignment(self, **kwargs):
        return type("MockAssignment", (), {"id": self._uuid.uuid4()})()
