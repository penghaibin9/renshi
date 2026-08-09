"""
hr_external/integrations/hr03.py —— HR03 Person/StaffMaster Provider（S2，00 §95 HR03→HR08）。

HR03 身份服务已交付（hr_staff），直接复用：
- PersonProvider: by_id / identity_match / create_person（复用 hr_staff.services.person_identity_service）
- StaffMasterProvider: 外聘目录投影需要 Staff ID 时通过 StaffMasterService 建立 HrStaffMaster
  （worker_kind=EXTERNAL 标记由 HR08 侧维护；regular_employee 等默认 false，S9 落地投影）。

跨域写纪律：HR08 不 import HR03 authority model 直接 .save()；
只调用 HR03 的 domain service（00 §14 跨域写合同）。
"""

from __future__ import annotations

from typing import Optional

from hr_external.integrations.base import BaseProvider, ProviderResult, ProviderStatus


class PersonProvider(BaseProvider):
    owner_domain = "HR03"
    sensitivity = "HIGH_SENSITIVE"  # 身份证/生日等；调用方必须按 HR03 权限策略二次裁剪

    def by_id(self, *, tenant_id: int, person_id) -> ProviderResult:
        """按 HR03 HrPerson id 读取基础身份（name/preferred_name 等）。"""
        self._require_tenant(tenant_id)
        from hr_staff.models import HrPerson

        person = HrPerson.objects.filter(tenant_id=tenant_id, id=person_id).first()
        if person is None:
            return ProviderResult(
                status=ProviderStatus.NOT_APPLICABLE,
                error_code="EXTERNAL_PROFILE_NOT_FOUND",
                error_message="person not found in tenant",
            )
        return ProviderResult(
            status=ProviderStatus.OK,
            data={
                "personId": str(person.id),
                "personUid": str(person.person_uid),
                "legalName": person.legal_name,
                "preferredName": person.preferred_name,
            },
            source_version="hr03.hrperson.1",
        )

    def create_person(
        self,
        *,
        tenant_id: int,
        legal_name: str,
        preferred_name: str = "",
        gender_code: Optional[str] = None,
        birth_date=None,
        nationality_code: str = "",
        document_number: Optional[str] = None,
        document_type: str = "NATIONAL_ID",
        contacts: Optional[list] = None,
    ) -> ProviderResult:
        """创建 Person（复用 HR03 PersonIdentityService；HARD 幂等、LIKELY 抛人工去重）。

        生产级（A28）：HR03 的重复检测异常必须转为可读 ProviderResult（不是 500）：
        - LIKELY 命中 → NOT_APPLICABLE + PERSON_DUPLICATE_REVIEW_REQUIRED（需人工去重）；
        - HARD 命中 → 返回已有 person（幂等合并，不重复建）。
        """
        self._require_tenant(tenant_id)
        from hr_staff.services.person_identity_service import (
            PersonDuplicateReviewRequired,
            PersonIdentityService,
        )

        service = PersonIdentityService()
        try:
            person = service.create_person_with_identity(
                tenant_id=tenant_id,
                legal_name=legal_name,
                preferred_name=preferred_name,
                gender_code=gender_code,
                birth_date=birth_date,
                nationality_code=nationality_code,
                document_type=document_type,
                document_number=document_number,
                contacts=contacts,
            )
        except PersonDuplicateReviewRequired:
            return ProviderResult(
                status=ProviderStatus.NOT_APPLICABLE,
                error_code="PERSON_DUPLICATE_REVIEW_REQUIRED",
                error_message="候选人与现有人员疑似重复，需人工去重确认（不自动合并）",
                source_version="hr03.person_identity.1",
            )
        return ProviderResult(
            status=ProviderStatus.OK,
            data={"personId": str(person.id), "personUid": str(person.person_uid)},
            source_version="hr03.person_identity.1",
        )

    def identity_match(self, *, tenant_id: int, document_number: str, legal_name: str, birth_date=None) -> ProviderResult:
        """身份去重（复用 HR03 PersonIdentityService.find_duplicate）。"""
        self._require_tenant(tenant_id)
        from hr_staff.services.person_identity_service import PersonIdentityService

        service = PersonIdentityService()
        result = service.find_duplicate(
            tenant_id, document_number=document_number, legal_name=legal_name, birth_date=birth_date
        )
        return ProviderResult(
            status=ProviderStatus.OK,
            data={
                "level": result.level,
                "existingPersonId": result.existing_person_id,
                "matchReasons": result.match_reasons,
            },
            source_version="hr03.person_identity.1",
        )


class StaffMasterProvider(BaseProvider):
    """外聘目录投影（§6.3）：需要 Staff ID 时建立 HrStaffMaster（source 受控）。"""

    owner_domain = "HR03"

    def create_staff_master(
        self,
        *,
        tenant_id: int,
        person_id,
        staff_category_code: str = "TEACHER",
        staff_no: Optional[str] = None,
        source: str = "HR_ENTERED",
    ) -> ProviderResult:
        self._require_tenant(tenant_id)
        from hr_staff.services.staff_master_service import StaffMasterService

        service = StaffMasterService()
        staff = service.create_staff(
            tenant_id=tenant_id,
            person_id=person_id,
            staff_category_code=staff_category_code,
            staff_no=staff_no,
            source=source,
        )
        return ProviderResult(
            status=ProviderStatus.OK,
            data={"staffId": str(staff.id), "staffNo": staff.staff_no},
            source_version="hr03.staff_master.1",
        )

    def get_staff_by_legacy(self, *, tenant_id: int, legacy_employee_id: int) -> ProviderResult:
        self._require_tenant(tenant_id)
        from hr_staff.services.staff_master_service import StaffMasterService

        service = StaffMasterService()
        staff = service.get_by_legacy_employee(tenant_id, legacy_employee_id)
        if staff is None:
            return ProviderResult(
                status=ProviderStatus.NOT_APPLICABLE,
                error_code="STAFF_NOT_FOUND",
                error_message="no staff master for legacy employee",
            )
        return ProviderResult(
            status=ProviderStatus.OK,
            data={"staffId": str(staff.id), "staffNo": staff.staff_no},
            source_version="hr03.staff_master.1",
        )
