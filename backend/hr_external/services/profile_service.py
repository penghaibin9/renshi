"""
hr_external/services/profile_service.py —— external_teacher_no 编号 + Profile 创建（S2，总册 §16/§17）。

- external_teacher_no 为 tenant-scoped 序列（建议 EXT2026000123）；不是正式员工工号（§17）。
- 同一 tenant 同一 person 一份 Profile（unique constraint + service 校验）。
- 事务内行锁防并发重复（同 tenant 唯一约束兜底）。
"""

from __future__ import annotations

import re
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_external.models import HrExternalTeacherProfile


class DuplicateProfile(Exception):
    code = "EXTERNAL_DUPLICATE_PROFILE"


class ExternalTeacherNumberService:
    """tenant-scoped 外聘编号生成。"""

    def __init__(self, prefix: str = "EXT", width: int = 6):
        self.prefix = prefix
        self.width = max(1, width)

    def next_external_no(self, tenant_id: int, year: Optional[int] = None) -> str:
        year = year or timezone.localdate().year
        pattern = re.compile(rf"^{self.prefix}{year}(?P<num>\d+)$")
        qs = HrExternalTeacherProfile.objects.filter(tenant_id=tenant_id)
        with transaction.atomic():
            locked = list(qs.select_for_update().values_list("external_teacher_no", flat=True)[:20000])
            max_num = 0
            for no in locked:
                m = pattern.match(no or "")
                if m:
                    try:
                        max_num = max(max_num, int(m.group("num")))
                    except ValueError:
                        continue
            return f"{self.prefix}{year}{(max_num + 1):0{self.width}d}"


class CategoryInvalid(Exception):
    code = "EXTERNAL_CATEGORY_INVALID"


class ProfileService:
    def __init__(self, number_service: Optional[ExternalTeacherNumberService] = None):
        self.number_service = number_service or ExternalTeacherNumberService()

    @transaction.atomic
    def create_profile(
        self,
        *,
        tenant_id: int,
        person_id,
        primary_category_code: Optional[str] = None,
        source_organization_name: str = "",
        source_organization_type: str = "",
        source_position_title: str = "",
        industry_domain: str = "",
        expertise_tags: Optional[list] = None,
        highest_professional_title: str = "",
        highest_skill_level: str = "",
        candidate_pool_status: str = "AVAILABLE",
        source: str = "HR_ENTERED",
    ) -> HrExternalTeacherProfile:
        if HrExternalTeacherProfile.objects.filter(
            tenant_id=tenant_id, person_id_id=person_id
        ).exists():
            raise DuplicateProfile("person already has an external profile in this tenant")

        category = None
        if primary_category_code:
            from hr_external.models import HrExternalCategory

            category = HrExternalCategory.objects.filter(
                tenant_id=tenant_id, code=primary_category_code, is_active=True
            ).first()
            if category is None:
                raise CategoryInvalid("external category invalid for tenant")

        external_no = self.number_service.next_external_no(tenant_id)
        return HrExternalTeacherProfile.objects.create(
            tenant_id=tenant_id,
            person_id_id=person_id,
            external_teacher_no=external_no,
            primary_category=category,
            source_organization_name=source_organization_name,
            source_organization_type=source_organization_type,
            source_position_title=source_position_title,
            industry_domain=industry_domain,
            expertise_tags=expertise_tags or [],
            highest_professional_title=highest_professional_title,
            highest_skill_level=highest_skill_level,
            candidate_pool_status=candidate_pool_status,
            source=source,
        )

    def get_by_person(self, tenant_id: int, person_id) -> Optional[HrExternalTeacherProfile]:
        return HrExternalTeacherProfile.objects.filter(
            tenant_id=tenant_id, person_id_id=person_id
        ).first()
